"""The Identity module's public contract for **other** backend modules
(spec section 19). When the Onboarding module is built, for example, its
"approve doctor application" use case should call

    await identity_command_service.replace_role(
        user_id, "DOCTOR_APPLICANT", "DOCTOR", changed_by=reviewer_id
    )

rather than importing Identity's repositories or ORM models directly
(spec section 19.3: "Other modules must not write directly to identity
tables"). Everything here is a thin, explicitly-named wrapper around
`RoleService` / the read repositories — see spec 19.1/19.2 for the exact
method list this mirrors.
"""

from __future__ import annotations

import uuid

from app.modules.identity.application.role_service import RoleService
from app.modules.identity.domain.enums import AccountStatus
from app.modules.identity.domain.repositories import RoleRepository, UserRepository


class IdentityQueryService:
    def __init__(self, user_repo: UserRepository, role_repo: RoleRepository) -> None:
        self._users = user_repo
        self._roles = role_repo

    async def get_user(self, user_id: uuid.UUID):
        return await self._users.get_by_id(user_id)

    async def get_user_roles(self, user_id: uuid.UUID) -> list[str]:
        rows = await self._roles.list_active_user_roles(user_id)
        return [role.code for _, role in rows]

    async def has_role(self, user_id: uuid.UUID, role_code: str) -> bool:
        return role_code in await self.get_user_roles(user_id)

    async def get_user_permissions(self, user_id: uuid.UUID) -> list[str]:
        return sorted(await self._roles.get_effective_permissions(user_id))

    async def is_user_active(self, user_id: uuid.UUID) -> bool:
        user = await self._users.get_by_id(user_id)
        return user is not None and user.account_status == AccountStatus.ACTIVE.value

    async def is_email_verified(self, user_id: uuid.UUID) -> bool:
        user = await self._users.get_by_id(user_id)
        return bool(user and user.email_verified)

    async def is_mobile_verified(self, user_id: uuid.UUID) -> bool:
        user = await self._users.get_by_id(user_id)
        return bool(user and user.mobile_verified)


class IdentityCommandService:
    def __init__(self, role_service: RoleService) -> None:
        self._role_service = role_service

    async def assign_role(
        self, user_id: uuid.UUID, role_code: str, assigned_by: uuid.UUID | None
    ) -> None:
        await self._role_service.assign_role(user_id, role_code, assigned_by)

    async def revoke_role(
        self, user_id: uuid.UUID, role_code: str, revoked_by: uuid.UUID | None, reason: str | None = None
    ) -> None:
        await self._role_service.revoke_role(user_id, role_code, revoked_by, reason)

    async def replace_role(
        self, user_id: uuid.UUID, old_role_code: str, new_role_code: str, changed_by: uuid.UUID | None
    ) -> None:
        await self._role_service.replace_role(user_id, old_role_code, new_role_code, changed_by)

    async def suspend_user(
        self, user_id: uuid.UUID, reason: str, suspended_by: uuid.UUID | None
    ) -> None:
        await self._role_service.suspend_user(user_id, reason, suspended_by)

    async def activate_user(self, user_id: uuid.UUID, activated_by: uuid.UUID | None) -> None:
        await self._role_service.activate_user(user_id, activated_by)

    async def revoke_all_sessions(self, user_id: uuid.UUID, reason: str) -> None:
        await self._role_service.revoke_all_sessions(user_id, reason)

    async def increment_token_version(self, user_id: uuid.UUID) -> None:
        await self._role_service.increment_token_version(user_id)
