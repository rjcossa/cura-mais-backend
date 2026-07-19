"""Providers module's outbox dispatcher. Thin wrapper around the shared
`OutboxDispatcher` (`app/core/outbox.py`), same shape as Identity's
(`app.modules.identity.application.outbox_dispatcher`) — Providers is a
receiver in the Identity/Onboarding integration (see
`infrastructure/provider_port_adapter.py`), not an initiator, so there's
no `postApprovalAction`-style second concern to deliver here, only
`notificationCommand` rows.
"""

from __future__ import annotations

from app.core.database import get_session_factory
from app.core.notifications import get_email_adapter, get_sms_adapter
from app.core.outbox import OutboxDispatcher
from app.modules.providers.domain.models import EventOutbox

_dispatcher: OutboxDispatcher | None = None


async def _deliver(row: EventOutbox, _session) -> None:
    payload = row.payload or {}
    command = payload.get("notificationCommand")
    if not command:
        return  # Pure audit/event row — nothing to deliver.

    channel = payload.get("channel")
    destination = payload.get("destination")
    parameters = payload.get("parameters", {})
    if not destination:
        return

    if channel == "SMS":
        await get_sms_adapter().send(destination=destination, template_code=command, parameters=parameters)
    elif channel == "EMAIL":
        await get_email_adapter().send(destination=destination, template_code=command, parameters=parameters)


def _get_dispatcher() -> OutboxDispatcher:
    global _dispatcher
    if _dispatcher is None:
        _dispatcher = OutboxDispatcher(
            name="providers",
            session_factory=get_session_factory(),
            model=EventOutbox,
            deliver=_deliver,
        )
    return _dispatcher


async def dispatch_once() -> int:
    return await _get_dispatcher().dispatch_once()


async def run_polling_loop(interval_seconds: float = 2.0, stop_event=None) -> None:
    await _get_dispatcher().run_polling_loop(interval_seconds, stop_event)
