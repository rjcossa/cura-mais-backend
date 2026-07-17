"""Role/permission administration and account-status lifecycle
(spec sections 16, 19.2's `suspendUser`/`activateUser`/`revokeAllSessions`).
"""

from __future__ import annotations

import datetime
import uuid

from app.modules.identity.domain.enums import AccountStatus
from app.modules.identity.domain.events import IdentityEvent
from app.modules.identity.domain.exceptions import IdentityError
from app.modules.identity.domain.models import IdentitySecurityEvent, User, UserRole
from app.modules.identity.domain.repositories import (
    OutboxRepository,
    RoleRepository,
    SecurityLogRepository,
    SessionRepository,
    UserRepository,
)


class RoleService:
    def __init__(
        self,
        user_repo: UserRepository,
        role_repo: RoleRepository,
        session_repo: SessionRepository,
        security_log_repo: SecurityLogRepository,
        outbox_repo: OutboxRepository,
    ) -> None:
        self._users = user_repo
        self._roles = role_repo
        self._sessions = session_repo
        self._security_log = security_log_repo
        self._outbox = outbox_repo

    # --- Queries (spec 19.1 IdentityQueryService) -----------------------

    async def get_user_roles(self, user_id: uuid.UUID) -> list[str]:
        rows = await self._roles.list_active_user_roles(user_id)
        return [role.code for _, role in rows]

    async def get_user_permissions(self, user_id: uuid.UUID) -> list[str]:
        return sorted(await self._roles.get_effective_permissions(user_id))

    # --- Commands (spec 16.3-16.5, 19.2 IdentityCommandService) ----------

    async def assign_role(
        self,
        user_id: uuid.UUID,
        role_code: str,
        assigned_by: uuid.UUID | None,
        *,
        expires_at: datetime.datetime | None = None,
        reason: str | None = None,
    ) -> UserRole:
        user = await self._require_user(user_id)
        role = await self._roles.get_role_by_code(role_code)
        if role is None:
            raise IdentityError.for_code("ROLE_NOT_FOUND")

        existing = await self._roles.get_active_user_role(user_id, role_code)
        if existing is not None:
            raise IdentityError.for_code("ROLE_ALREADY_ASSIGNED")

        user_role = UserRole(
            user_id=user_id,
            role_id=role.id,
            active=True,
            assigned_by=assigned_by,
            expires_at=expires_at,
            revoke_reason=None,
        )
        await self._roles.add_user_role(user_role)
        user.token_version += 1

        await self._security_log.add_security_event(
            IdentitySecurityEvent(
                user_id=user_id,
                event_type="UserRoleAssigned",
                severity="INFO",
                details={"roleCode": role_code, "assignedBy": str(assigned_by), "reason": reason},
            )
        )
        await self._outbox.enqueue(
            IdentityEvent.USER_ROLE_ASSIGNED,
            {"userId": str(user_id), "roleCode": role_code},
            aggregate_id=user_id,
        )
        return user_role

    async def revoke_role(
        self, user_id: uuid.UUID, role_code: str, revoked_by: uuid.UUID | None, reason: str | None = None
    ) -> None:
        user = await self._require_user(user_id)
        existing = await self._roles.get_active_user_role(user_id, role_code)
        if existing is None:
            raise IdentityError.for_code("ROLE_NOT_ASSIGNED")

        existing.active = False
        existing.revoked_at = datetime.datetime.now(datetime.UTC)
        existing.revoked_by = revoked_by
        existing.revoke_reason = reason
        user.token_version += 1

        await self._security_log.add_security_event(
            IdentitySecurityEvent(
                user_id=user_id,
                event_type="UserRoleRevoked",
                severity="INFO",
                details={"roleCode": role_code, "revokedBy": str(revoked_by), "reason": reason},
            )
        )
        await self._outbox.enqueue(
            IdentityEvent.USER_ROLE_REVOKED,
            {"userId": str(user_id), "roleCode": role_code},
            aggregate_id=user_id,
        )

    async def replace_role(
        self, user_id: uuid.UUID, old_role_code: str, new_role_code: str, changed_by: uuid.UUID | None
    ) -> None:
        """E.g. DOCTOR_APPLICANT -> DOCTOR on onboarding approval (spec 16.3).
        Intended to be called by the (future) Onboarding module via the
        `IdentityCommandService` port, not directly by HTTP clients.
        """
        user = await self._require_user(user_id)
        new_role = await self._roles.get_role_by_code(new_role_code)
        if new_role is None:
            raise IdentityError.for_code("ROLE_NOT_FOUND")

        old_assignment = await self._roles.get_active_user_role(user_id, old_role_code)
        if old_assignment is not None:
            old_assignment.active = False
            old_assignment.revoked_at = datetime.datetime.now(datetime.UTC)
            old_assignment.revoked_by = changed_by
            old_assignment.revoke_reason = f"REPLACED_BY_{new_role_code}"

        already_has_new = await self._roles.get_active_user_role(user_id, new_role_code)
        if already_has_new is None:
            await self._roles.add_user_role(
                UserRole(user_id=user_id, role_id=new_role.id, active=True, assigned_by=changed_by)
            )

        user.token_version += 1

        await self._security_log.add_security_event(
            IdentitySecurityEvent(
                user_id=user_id,
                event_type="UserRoleChanged",
                severity="INFO",
                details={"from": old_role_code, "to": new_role_code, "changedBy": str(changed_by)},
            )
        )
        await self._outbox.enqueue(
            IdentityEvent.USER_ROLE_CHANGED,
            {"userId": str(user_id), "from": old_role_code, "to": new_role_code},
            aggregate_id=user_id,
        )

    async def suspend_user(
        self, user_id: uuid.UUID, reason: str, suspended_by: uuid.UUID | None
    ) -> None:
        user = await self._require_user(user_id)
        user.account_status = AccountStatus.SUSPENDED.value
        user.token_version += 1
        await self._sessions.revoke_all_for_user(user_id, reason="ACCOUNT_SUSPENDED")

        await self._security_log.add_security_event(
            IdentitySecurityEvent(
                user_id=user_id,
                event_type="UserSuspended",
                severity="HIGH",
                details={"reason": reason, "suspendedBy": str(suspended_by)},
            )
        )
        await self._outbox.enqueue(
            IdentityEvent.USER_SUSPENDED, {"userId": str(user_id), "reason": reason}, aggregate_id=user_id
        )

    async def activate_user(self, user_id: uuid.UUID, activated_by: uuid.UUID | None) -> None:
        user = await self._require_user(user_id)
        user.account_status = AccountStatus.ACTIVE.value
        user.failed_login_attempts = 0
        user.locked_until = None

        await self._security_log.add_security_event(
            IdentitySecurityEvent(
                user_id=user_id,
                event_type="UserActivated",
                severity="INFO",
                details={"activatedBy": str(activated_by)},
            )
        )
        await self._outbox.enqueue(
            IdentityEvent.USER_ACTIVATED, {"userId": str(user_id)}, aggregate_id=user_id
        )

    async def revoke_all_sessions(self, user_id: uuid.UUID, reason: str) -> None:
        user = await self._require_user(user_id)
        await self._sessions.revoke_all_for_user(user_id, reason=reason)
        user.token_version += 1

    async def increment_token_version(self, user_id: uuid.UUID) -> None:
        user = await self._require_user(user_id)
        user.token_version += 1

    async def _require_user(self, user_id: uuid.UUID) -> User:
        user = await self._users.get_by_id(user_id)
        if user is None:
            raise IdentityError.for_code("USER_NOT_FOUND")
        return user
