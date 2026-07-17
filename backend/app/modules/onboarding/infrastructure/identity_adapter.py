"""Identity module integration (spec section 21.3) — genuinely real, not
mocked: it wraps Identity's own `IdentityQueryService` /
`IdentityCommandService` (`app.modules.identity.application.identity_ports`),
which were built with exactly this cross-module contract in mind. This is
the payoff of that design: Onboarding never touches Identity's tables,
repositories, or ORM models directly (per Identity spec 19.3 and
Onboarding spec 2.2's "must not directly update tables owned by those
modules") — only this thin adapter, calling the same public ports a
same-process caller would.
"""

from __future__ import annotations

import uuid
from typing import Protocol

from app.modules.identity.application.identity_ports import IdentityCommandService, IdentityQueryService


class IdentityPort(Protocol):
    async def is_user_active(self, user_id: uuid.UUID) -> bool: ...
    async def has_role(self, user_id: uuid.UUID, role_code: str) -> bool: ...
    async def replace_role(
        self, user_id: uuid.UUID, old_role_code: str, new_role_code: str, changed_by: uuid.UUID | None
    ) -> None: ...
    async def assign_role(self, user_id: uuid.UUID, role_code: str, changed_by: uuid.UUID | None) -> None: ...
    async def revoke_role(
        self, user_id: uuid.UUID, role_code: str, changed_by: uuid.UUID | None, reason: str | None = None
    ) -> None: ...


class IdentityAdapter:
    def __init__(self, query_service: IdentityQueryService, command_service: IdentityCommandService) -> None:
        self._query = query_service
        self._command = command_service

    async def is_user_active(self, user_id: uuid.UUID) -> bool:
        return await self._query.is_user_active(user_id)

    async def has_role(self, user_id: uuid.UUID, role_code: str) -> bool:
        return await self._query.has_role(user_id, role_code)

    async def replace_role(
        self, user_id: uuid.UUID, old_role_code: str, new_role_code: str, changed_by: uuid.UUID | None
    ) -> None:
        await self._command.replace_role(user_id, old_role_code, new_role_code, changed_by)

    async def assign_role(self, user_id: uuid.UUID, role_code: str, changed_by: uuid.UUID | None) -> None:
        await self._command.assign_role(user_id, role_code, changed_by)

    async def revoke_role(
        self, user_id: uuid.UUID, role_code: str, changed_by: uuid.UUID | None, reason: str | None = None
    ) -> None:
        await self._command.revoke_role(user_id, role_code, changed_by, reason)


# Maps an Onboarding applicant type to the Identity role transition that
# should happen on approval (APPLICANT role -> approved role). Hospital/
# Clinic/Pharmacy applicants don't have a distinct "*_APPLICANT" role in
# Identity today (only Doctor/Nutritionist do — see Identity spec 6.1's
# "MVP may initially expose patient and doctor registration only"), so
# for those types this adapter *assigns* the admin role directly rather
# than replacing an applicant-only role. When Identity adds dedicated
# applicant roles for institutions, only this table changes.
APPROVAL_ROLE_TRANSITIONS: dict[str, tuple[str | None, str]] = {
    "DOCTOR": ("DOCTOR_APPLICANT", "DOCTOR"),
    "NUTRITIONIST": ("NUTRITIONIST_APPLICANT", "NUTRITIONIST"),
    "HOSPITAL": (None, "HOSPITAL_ADMIN"),
    "CLINIC": (None, "HOSPITAL_ADMIN"),
    "PHARMACY": (None, "PHARMACY_ADMIN"),
}


async def apply_approval_role_transition(
    identity: IdentityPort, *, applicant_type: str, applicant_user_id: uuid.UUID, changed_by: uuid.UUID | None
) -> None:
    transition = APPROVAL_ROLE_TRANSITIONS.get(applicant_type)
    if transition is None:
        return
    old_role, new_role = transition
    if old_role is not None and await identity.has_role(applicant_user_id, old_role):
        await identity.replace_role(applicant_user_id, old_role, new_role, changed_by)
    elif not await identity.has_role(applicant_user_id, new_role):
        await identity.assign_role(applicant_user_id, new_role, changed_by)
