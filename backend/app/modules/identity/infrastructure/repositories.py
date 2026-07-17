"""SQLAlchemy implementations of the repository ports declared in
`domain/repositories.py`. This is the only file (besides Alembic
migrations) that should contain raw SQLAlchemy `select`/`update` calls for
the Identity module.
"""

from __future__ import annotations

import datetime
import uuid

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.identity.domain.models import (
    AuthenticationIdentity,
    EventOutbox,
    IdentitySecurityEvent,
    LoginAttempt,
    PasswordHistory,
    Permission,
    Role,
    RolePermission,
    User,
    UserMfaMethod,
    UserRecoveryCode,
    UserRole,
    UserSession,
    VerificationToken,
)


class SqlAlchemyUserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, user_id: uuid.UUID) -> User | None:
        stmt = select(User).where(User.id == user_id, User.deleted_at.is_(None))
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def get_by_email(self, email: str) -> User | None:
        stmt = select(User).where(User.email == email, User.deleted_at.is_(None))
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def get_by_mobile(self, mobile_number: str) -> User | None:
        stmt = select(User).where(
            User.mobile_number == mobile_number, User.deleted_at.is_(None)
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def add(self, user: User) -> None:
        self._session.add(user)
        await self._session.flush()

    async def get_auth_identity(
        self, provider: str, provider_subject: str
    ) -> AuthenticationIdentity | None:
        stmt = select(AuthenticationIdentity).where(
            AuthenticationIdentity.provider == provider,
            AuthenticationIdentity.provider_subject == provider_subject,
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def list_auth_identities(self, user_id: uuid.UUID) -> list[AuthenticationIdentity]:
        stmt = select(AuthenticationIdentity).where(AuthenticationIdentity.user_id == user_id)
        return list((await self._session.execute(stmt)).scalars().all())

    async def add_auth_identity(self, identity: AuthenticationIdentity) -> None:
        self._session.add(identity)
        await self._session.flush()

    async def delete_auth_identity(self, identity: AuthenticationIdentity) -> None:
        await self._session.delete(identity)
        await self._session.flush()

    async def add_password_history(self, entry: PasswordHistory) -> None:
        self._session.add(entry)
        await self._session.flush()

    async def list_recent_password_hashes(self, user_id: uuid.UUID, limit: int) -> list[str]:
        stmt = (
            select(PasswordHistory.password_hash)
            .where(PasswordHistory.user_id == user_id)
            .order_by(PasswordHistory.created_at.desc())
            .limit(limit)
        )
        return list((await self._session.execute(stmt)).scalars().all())


class SqlAlchemyRoleRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_role_by_code(self, code: str) -> Role | None:
        stmt = select(Role).where(Role.code == code, Role.active.is_(True))
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def get_active_user_role(self, user_id: uuid.UUID, role_code: str) -> UserRole | None:
        stmt = (
            select(UserRole)
            .join(Role, Role.id == UserRole.role_id)
            .where(
                UserRole.user_id == user_id,
                Role.code == role_code,
                UserRole.active.is_(True),
                UserRole.revoked_at.is_(None),
            )
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def list_active_user_roles(self, user_id: uuid.UUID) -> list[tuple[UserRole, Role]]:
        now = datetime.datetime.now(datetime.UTC)
        stmt = (
            select(UserRole, Role)
            .join(Role, Role.id == UserRole.role_id)
            .where(
                UserRole.user_id == user_id,
                UserRole.active.is_(True),
                UserRole.revoked_at.is_(None),
                (UserRole.expires_at.is_(None)) | (UserRole.expires_at > now),
            )
        )
        return [(row[0], row[1]) for row in (await self._session.execute(stmt)).all()]

    async def add_user_role(self, user_role: UserRole) -> None:
        self._session.add(user_role)
        await self._session.flush()

    async def get_effective_permissions(self, user_id: uuid.UUID) -> set[str]:
        now = datetime.datetime.now(datetime.UTC)
        stmt = (
            select(Permission.code)
            .join(RolePermission, RolePermission.permission_id == Permission.id)
            .join(Role, Role.id == RolePermission.role_id)
            .join(UserRole, UserRole.role_id == Role.id)
            .where(
                UserRole.user_id == user_id,
                UserRole.active.is_(True),
                UserRole.revoked_at.is_(None),
                Role.active.is_(True),
                (UserRole.expires_at.is_(None)) | (UserRole.expires_at > now),
            )
            .distinct()
        )
        return set((await self._session.execute(stmt)).scalars().all())


class SqlAlchemySessionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, user_session: UserSession) -> None:
        self._session.add(user_session)
        await self._session.flush()

    async def get_by_refresh_hash(self, refresh_token_hash: str) -> UserSession | None:
        stmt = select(UserSession).where(UserSession.refresh_token_hash == refresh_token_hash)
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def get_by_id(self, session_id: uuid.UUID) -> UserSession | None:
        stmt = select(UserSession).where(UserSession.id == session_id)
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def list_active_family_heads(self, user_id: uuid.UUID) -> list[UserSession]:
        now = datetime.datetime.now(datetime.UTC)
        stmt = select(UserSession).where(
            UserSession.user_id == user_id,
            UserSession.revoked_at.is_(None),
            UserSession.replaced_by_session_id.is_(None),
            UserSession.expires_at > now,
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def get_family_created_at(self, token_family_id: uuid.UUID) -> datetime.datetime | None:
        stmt = select(func.min(UserSession.issued_at)).where(
            UserSession.token_family_id == token_family_id
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def revoke(self, user_session: UserSession, reason: str) -> None:
        user_session.revoked_at = datetime.datetime.now(datetime.UTC)
        user_session.revoke_reason = reason
        await self._session.flush()

    async def revoke_all_for_user(self, user_id: uuid.UUID, reason: str) -> int:
        stmt = (
            update(UserSession)
            .where(UserSession.user_id == user_id, UserSession.revoked_at.is_(None))
            .values(revoked_at=func.now(), revoke_reason=reason)
        )
        result = await self._session.execute(stmt)
        return result.rowcount or 0

    async def revoke_all_for_user_except(
        self, user_id: uuid.UUID, keep_session_id: uuid.UUID, reason: str
    ) -> int:
        stmt = (
            update(UserSession)
            .where(
                UserSession.user_id == user_id,
                UserSession.revoked_at.is_(None),
                UserSession.id != keep_session_id,
            )
            .values(revoked_at=func.now(), revoke_reason=reason)
        )
        result = await self._session.execute(stmt)
        return result.rowcount or 0

    async def revoke_family(self, token_family_id: uuid.UUID, reason: str) -> int:
        stmt = (
            update(UserSession)
            .where(
                UserSession.token_family_id == token_family_id,
                UserSession.revoked_at.is_(None),
            )
            .values(revoked_at=func.now(), revoke_reason=reason)
        )
        result = await self._session.execute(stmt)
        return result.rowcount or 0


class SqlAlchemyVerificationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, token: VerificationToken) -> None:
        self._session.add(token)
        await self._session.flush()

    async def get_by_hash(self, token_hash: str) -> VerificationToken | None:
        stmt = select(VerificationToken).where(VerificationToken.token_hash == token_hash)
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def get_by_id(self, token_id: uuid.UUID) -> VerificationToken | None:
        stmt = select(VerificationToken).where(VerificationToken.id == token_id)
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def get_active_for_user(
        self, user_id: uuid.UUID, token_type: str
    ) -> VerificationToken | None:
        stmt = (
            select(VerificationToken)
            .where(
                VerificationToken.user_id == user_id,
                VerificationToken.token_type == token_type,
                VerificationToken.used_at.is_(None),
                VerificationToken.invalidated_at.is_(None),
            )
            .order_by(VerificationToken.created_at.desc())
            .limit(1)
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def invalidate_active_for_user(self, user_id: uuid.UUID, token_type: str) -> None:
        stmt = (
            update(VerificationToken)
            .where(
                VerificationToken.user_id == user_id,
                VerificationToken.token_type == token_type,
                VerificationToken.used_at.is_(None),
                VerificationToken.invalidated_at.is_(None),
            )
            .values(invalidated_at=func.now())
        )
        await self._session.execute(stmt)


class SqlAlchemyMfaRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add_method(self, method: UserMfaMethod) -> None:
        self._session.add(method)
        await self._session.flush()

    async def get_method_by_id(self, method_id: uuid.UUID) -> UserMfaMethod | None:
        stmt = select(UserMfaMethod).where(UserMfaMethod.id == method_id)
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def list_enabled_methods(self, user_id: uuid.UUID) -> list[UserMfaMethod]:
        stmt = select(UserMfaMethod).where(
            UserMfaMethod.user_id == user_id,
            UserMfaMethod.enabled.is_(True),
            UserMfaMethod.disabled_at.is_(None),
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def add_recovery_codes(self, codes: list[UserRecoveryCode]) -> None:
        self._session.add_all(codes)
        await self._session.flush()

    async def get_recovery_code_by_hash(
        self, user_id: uuid.UUID, code_hash: str
    ) -> UserRecoveryCode | None:
        stmt = select(UserRecoveryCode).where(
            UserRecoveryCode.user_id == user_id,
            UserRecoveryCode.code_hash == code_hash,
            UserRecoveryCode.used_at.is_(None),
            UserRecoveryCode.invalidated_at.is_(None),
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def invalidate_unused_recovery_codes(self, user_id: uuid.UUID) -> None:
        stmt = (
            update(UserRecoveryCode)
            .where(
                UserRecoveryCode.user_id == user_id,
                UserRecoveryCode.used_at.is_(None),
                UserRecoveryCode.invalidated_at.is_(None),
            )
            .values(invalidated_at=func.now())
        )
        await self._session.execute(stmt)


class SqlAlchemySecurityLogRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add_login_attempt(self, attempt: LoginAttempt) -> None:
        self._session.add(attempt)
        await self._session.flush()

    async def add_security_event(self, event: IdentitySecurityEvent) -> None:
        self._session.add(event)
        await self._session.flush()


class SqlAlchemyOutboxRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def enqueue(
        self,
        event_type: str,
        payload: dict,
        *,
        aggregate_id: uuid.UUID | None = None,
        aggregate_type: str = "User",
    ) -> None:
        self._session.add(
            EventOutbox(
                event_type=event_type,
                aggregate_type=aggregate_type,
                aggregate_id=aggregate_id,
                payload=payload,
            )
        )
        await self._session.flush()
