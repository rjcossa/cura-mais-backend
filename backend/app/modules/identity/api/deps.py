"""FastAPI dependency wiring for the Identity module.

Every service factory below builds a fresh set of repositories bound to
the current request's `AsyncSession`. Repositories are cheap, stateless
wrappers, so there's no need for a heavier DI container — this is the
single place that knows how the module's object graph fits together.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.database import get_db
from app.core.exceptions import PermissionDeniedError, UnauthorizedError
from app.modules.identity.application.authentication_service import AuthenticationService
from app.modules.identity.application.identity_ports import (
    IdentityCommandService,
    IdentityQueryService,
)
from app.modules.identity.application.mfa_service import MfaService
from app.modules.identity.application.password_service import PasswordService
from app.modules.identity.application.registration_service import RegistrationService
from app.modules.identity.application.role_service import RoleService
from app.modules.identity.application.session_service import SessionService
from app.modules.identity.application.social_service import SocialAuthService
from app.modules.identity.application.tokens import (
    AccessTokenClaims,
    AccessTokenCodec,
    TokenService,
)
from app.modules.identity.application.user_service import UserService
from app.modules.identity.application.verification_service import VerificationService
from app.modules.identity.domain.enums import AccountStatus
from app.modules.identity.domain.models import User
from app.modules.identity.infrastructure.repositories import (
    SqlAlchemyMfaRepository,
    SqlAlchemyOutboxRepository,
    SqlAlchemyRoleRepository,
    SqlAlchemySecurityLogRepository,
    SqlAlchemySessionRepository,
    SqlAlchemyUserRepository,
    SqlAlchemyVerificationRepository,
)
from app.modules.identity.infrastructure.social_providers import (
    AppleIdentityProvider,
    FacebookIdentityProvider,
    GoogleIdentityProvider,
)

DbSession = Annotated[AsyncSession, Depends(get_db)]
SettingsDep = Annotated[Settings, Depends(get_settings)]

_bearer_scheme = HTTPBearer(auto_error=False, description="Access token issued by /auth/login or /auth/refresh")


def _repos(db: AsyncSession):
    return {
        "user": SqlAlchemyUserRepository(db),
        "role": SqlAlchemyRoleRepository(db),
        "session": SqlAlchemySessionRepository(db),
        "verification": SqlAlchemyVerificationRepository(db),
        "mfa": SqlAlchemyMfaRepository(db),
        "security_log": SqlAlchemySecurityLogRepository(db),
        "outbox": SqlAlchemyOutboxRepository(db),
    }


def get_token_service(db: DbSession, settings: SettingsDep) -> TokenService:
    r = _repos(db)
    return TokenService(settings, r["user"], r["role"], r["session"], r["security_log"], r["outbox"])


def get_mfa_service(db: DbSession, settings: SettingsDep) -> MfaService:
    r = _repos(db)
    return MfaService(
        settings, r["user"], r["role"], r["mfa"], r["verification"], r["security_log"], r["outbox"]
    )


def get_registration_service(db: DbSession, settings: SettingsDep) -> RegistrationService:
    r = _repos(db)
    return RegistrationService(
        settings, r["user"], r["role"], r["verification"], r["security_log"], r["outbox"]
    )


def get_authentication_service(db: DbSession, settings: SettingsDep) -> AuthenticationService:
    r = _repos(db)
    token_service = get_token_service(db, settings)
    mfa_service = get_mfa_service(db, settings)
    return AuthenticationService(
        settings, r["user"], r["mfa"], r["security_log"], r["outbox"], token_service, mfa_service
    )


def get_session_service(db: DbSession) -> SessionService:
    r = _repos(db)
    return SessionService(r["user"], r["session"], r["security_log"], r["outbox"])


def get_verification_service(db: DbSession, settings: SettingsDep) -> VerificationService:
    r = _repos(db)
    return VerificationService(settings, r["user"], r["verification"], r["outbox"])


def get_password_service(db: DbSession, settings: SettingsDep) -> PasswordService:
    r = _repos(db)
    return PasswordService(
        settings, r["user"], r["session"], r["verification"], r["security_log"], r["outbox"]
    )


def get_role_service(db: DbSession) -> RoleService:
    r = _repos(db)
    return RoleService(r["user"], r["role"], r["session"], r["security_log"], r["outbox"])


def get_user_service(db: DbSession, settings: SettingsDep) -> UserService:
    r = _repos(db)
    return UserService(
        settings, r["user"], r["role"], r["session"], r["verification"], r["security_log"], r["outbox"]
    )


def get_social_service(db: DbSession, settings: SettingsDep) -> SocialAuthService:
    r = _repos(db)
    token_service = get_token_service(db, settings)
    mfa_service = get_mfa_service(db, settings)
    providers = {
        "GOOGLE": GoogleIdentityProvider(settings),
        "APPLE": AppleIdentityProvider(settings),
        "FACEBOOK": FacebookIdentityProvider(settings),
    }
    return SocialAuthService(
        settings,
        r["user"],
        r["role"],
        r["mfa"],
        r["security_log"],
        r["outbox"],
        token_service,
        mfa_service,
        providers,
    )


def get_identity_query_service(db: DbSession) -> IdentityQueryService:
    r = _repos(db)
    return IdentityQueryService(r["user"], r["role"])


def get_identity_command_service(db: DbSession) -> IdentityCommandService:
    return IdentityCommandService(get_role_service(db))


# --- Authentication dependency -----------------------------------------


@dataclass(slots=True)
class AuthContext:
    user: User
    claims: AccessTokenClaims


async def get_auth_context(
    db: DbSession,
    settings: SettingsDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer_scheme)],
) -> AuthContext:
    if credentials is None or not credentials.credentials:
        raise UnauthorizedError("ACCESS_TOKEN_INVALID", "An access token is required.")

    codec = AccessTokenCodec(settings)
    claims = codec.decode(credentials.credentials)  # raises ACCESS_TOKEN_EXPIRED/INVALID

    user_repo = SqlAlchemyUserRepository(db)
    user = await user_repo.get_by_id(claims.subject)
    if user is None:
        raise UnauthorizedError("ACCESS_TOKEN_INVALID", "The account for this token no longer exists.")

    if user.account_status in {
        AccountStatus.SUSPENDED.value,
        AccountStatus.DEACTIVATED.value,
        AccountStatus.DELETED.value,
    }:
        raise UnauthorizedError("ACCESS_TOKEN_INVALID", "This account is no longer active.")

    if claims.token_version != user.token_version:
        # Password changed / all-sessions-revoked / role changed since this
        # token was issued (spec section 8.5).
        raise UnauthorizedError("ACCESS_TOKEN_INVALID", "This token is no longer valid. Please log in again.")

    return AuthContext(user=user, claims=claims)


CurrentAuth = Annotated[AuthContext, Depends(get_auth_context)]


def require_permission(permission_code: str):
    async def _dependency(auth: CurrentAuth) -> AuthContext:
        if permission_code not in auth.claims.permissions:
            raise PermissionDeniedError()
        return auth

    return _dependency
