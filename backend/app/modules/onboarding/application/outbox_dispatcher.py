"""Onboarding module's outbox dispatcher.

Thin wrapper around the shared `OutboxDispatcher` (`app/core/outbox.py`),
same "schema not migrated yet" handling as Identity's. Two kinds of
payloads are delivered:

1. `notificationCommand` — same as Identity, dispatched to the mock/SMTP
   adapters (`app.core.notifications`).
2. `postApprovalAction` — spec 16.2: "Identity and Provider activation
   should occur asynchronously after the approval transaction through
   reliable events." `DecisionService` never calls Identity/Provider/
   Institution directly; it enqueues one of these, and *this* dispatcher
   performs the actual role-transition / activation / suspension call
   once the approval transaction has safely committed.
"""

from __future__ import annotations

import uuid

from app.core.database import get_session_factory
from app.core.notifications import get_email_adapter, get_sms_adapter
from app.core.outbox import OutboxDispatcher
from app.modules.identity.application.identity_ports import IdentityCommandService, IdentityQueryService
from app.modules.identity.infrastructure.repositories import (
    SqlAlchemyRoleRepository,
    SqlAlchemyUserRepository,
)
from app.modules.onboarding.domain.models import EventOutbox
from app.modules.onboarding.infrastructure.identity_adapter import (
    IdentityAdapter,
    apply_approval_role_transition,
)
from app.shared.institution.port import get_institution_adapter
from app.shared.provider.port import get_provider_adapter

_dispatcher: OutboxDispatcher | None = None

_INSTITUTIONAL_TYPES = {"HOSPITAL", "CLINIC", "PHARMACY"}


async def _deliver(row: EventOutbox, session) -> None:
    payload = row.payload or {}

    action = payload.get("postApprovalAction")
    if action:
        await _handle_post_approval_action(payload, action, session)

    command = payload.get("notificationCommand")
    if command:
        channel = payload.get("channel")
        destination = payload.get("destination")
        parameters = payload.get("parameters", {})
        if destination and channel == "SMS":
            await get_sms_adapter().send(destination=destination, template_code=command, parameters=parameters)
        elif destination and channel == "EMAIL":
            await get_email_adapter().send(destination=destination, template_code=command, parameters=parameters)


async def _handle_post_approval_action(payload: dict, action: str, session) -> None:
    applicant_type = payload["applicantType"]
    applicant_user_id = uuid.UUID(payload["applicantUserId"])
    applicant_entity_id = uuid.UUID(payload["applicantEntityId"])
    reference = payload.get("approvalReference", "")
    changed_by = uuid.UUID(payload["decidedBy"]) if payload.get("decidedBy") else None

    identity = IdentityAdapter(
        IdentityQueryService(SqlAlchemyUserRepository(session), SqlAlchemyRoleRepository(session)),
        IdentityCommandService(_role_service(session)),
    )

    if action == "ACTIVATE":
        await apply_approval_role_transition(
            identity, applicant_type=applicant_type, applicant_user_id=applicant_user_id, changed_by=changed_by
        )
        if applicant_type in _INSTITUTIONAL_TYPES:
            await get_institution_adapter().activate_institution(applicant_entity_id, approval_reference=reference)
        else:
            await get_provider_adapter().activate_provider(applicant_entity_id, approval_reference=reference)

    elif action == "SUSPEND":
        reason = payload.get("reason", "")
        if applicant_type in _INSTITUTIONAL_TYPES:
            await get_institution_adapter().suspend_institution(applicant_entity_id, reason=reason)
        else:
            await get_provider_adapter().suspend_provider(applicant_entity_id, reason=reason)

    elif action == "REINSTATE":
        if applicant_type in _INSTITUTIONAL_TYPES:
            await get_institution_adapter().activate_institution(applicant_entity_id, approval_reference=reference)
        else:
            await get_provider_adapter().reinstate_provider(applicant_entity_id, approval_reference=reference)


def _role_service(session):
    from app.modules.identity.application.role_service import RoleService
    from app.modules.identity.infrastructure.repositories import (
        SqlAlchemyOutboxRepository as IdentityOutboxRepo,
    )
    from app.modules.identity.infrastructure.repositories import (
        SqlAlchemySecurityLogRepository,
        SqlAlchemySessionRepository,
    )

    return RoleService(
        SqlAlchemyUserRepository(session),
        SqlAlchemyRoleRepository(session),
        SqlAlchemySessionRepository(session),
        SqlAlchemySecurityLogRepository(session),
        IdentityOutboxRepo(session),
    )


def _get_dispatcher() -> OutboxDispatcher:
    global _dispatcher
    if _dispatcher is None:
        _dispatcher = OutboxDispatcher(
            name="onboarding",
            session_factory=get_session_factory(),
            model=EventOutbox,
            deliver=_deliver,
        )
    return _dispatcher


async def dispatch_once() -> int:
    return await _get_dispatcher().dispatch_once()


async def run_polling_loop(interval_seconds: float = 2.0, stop_event=None) -> None:
    await _get_dispatcher().run_polling_loop(interval_seconds, stop_event)
