"""Access token (JWT) issuance/verification and refresh token
issuance/rotation/reuse-detection (spec sections 8, 9).
"""

from __future__ import annotations

import datetime
import uuid
from dataclasses import dataclass
from functools import lru_cache

import jwt

from app.core.config import Settings
from app.modules.identity.application.security import generate_opaque_token, hash_opaque_token
from app.modules.identity.domain.events import IdentityEvent
from app.modules.identity.domain.exceptions import IdentityError
from app.modules.identity.domain.models import User, UserSession
from app.modules.identity.domain.repositories import (
    OutboxRepository,
    RoleRepository,
    SecurityLogRepository,
    SessionRepository,
    UserRepository,
)


@lru_cache
def _load_key(path: str) -> str:
    with open(path) as fh:
        return fh.read()


@dataclass(slots=True)
class AccessTokenClaims:
    subject: uuid.UUID
    session_id: uuid.UUID
    roles: list[str]
    permissions: list[str]
    email_verified: bool
    mobile_verified: bool
    mfa_verified: bool
    token_version: int
    jti: str


@dataclass(slots=True)
class DeviceInfo:
    device_id: str | None = None
    device_name: str | None = None
    platform: str | None = None
    app_version: str | None = None
    ip_address: str | None = None
    user_agent: str | None = None
    remember_me: bool = False


@dataclass(slots=True)
class IssuedSession:
    session: UserSession
    raw_refresh_token: str
    access_token: str
    access_token_expires_in: int


class AccessTokenCodec:
    """Pure JWT encode/decode — depends only on `Settings`, no repositories.
    Used directly by the auth dependency (`api/deps.py`) on every
    authenticated request, and composed into `TokenService` below for
    issuance.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def build_and_sign(
        self,
        *,
        user_id: uuid.UUID,
        session_id: uuid.UUID,
        roles: list[str],
        permissions: list[str],
        email_verified: bool,
        mobile_verified: bool,
        mfa_verified: bool,
        token_version: int,
    ) -> tuple[str, int]:
        now = datetime.datetime.now(datetime.UTC)
        expires_in = self._settings.access_token_expire_minutes * 60
        payload = {
            "sub": str(user_id),
            "sid": str(session_id),
            "roles": roles,
            "permissions": permissions,
            "email_verified": email_verified,
            "mobile_verified": mobile_verified,
            "mfa_verified": mfa_verified,
            "token_version": token_version,
            "iat": int(now.timestamp()),
            "nbf": int(now.timestamp()),
            "exp": int((now + datetime.timedelta(seconds=expires_in)).timestamp()),
            "iss": self._settings.jwt_issuer,
            "aud": self._settings.jwt_audience,
            "jti": str(uuid.uuid4()),
        }
        private_key = _load_key(str(self._settings.jwt_private_key_path))
        token = jwt.encode(payload, private_key, algorithm=self._settings.jwt_algorithm)
        return token, expires_in

    def decode(self, token: str) -> AccessTokenClaims:
        public_key = _load_key(str(self._settings.jwt_public_key_path))
        try:
            payload = jwt.decode(
                token,
                public_key,
                algorithms=[self._settings.jwt_algorithm],
                audience=self._settings.jwt_audience,
                issuer=self._settings.jwt_issuer,
            )
        except jwt.ExpiredSignatureError as exc:
            raise IdentityError.for_code("ACCESS_TOKEN_EXPIRED") from exc
        except jwt.PyJWTError as exc:
            raise IdentityError.for_code("ACCESS_TOKEN_INVALID") from exc

        return AccessTokenClaims(
            subject=uuid.UUID(payload["sub"]),
            session_id=uuid.UUID(payload["sid"]),
            roles=payload.get("roles", []),
            permissions=payload.get("permissions", []),
            email_verified=payload.get("email_verified", False),
            mobile_verified=payload.get("mobile_verified", False),
            mfa_verified=payload.get("mfa_verified", False),
            token_version=payload.get("token_version", 0),
            jti=payload.get("jti", ""),
        )


class TokenService:
    def __init__(
        self,
        settings: Settings,
        user_repo: UserRepository,
        role_repo: RoleRepository,
        session_repo: SessionRepository,
        security_log_repo: SecurityLogRepository,
        outbox_repo: OutboxRepository,
    ) -> None:
        self._settings = settings
        self._users = user_repo
        self._roles = role_repo
        self._sessions = session_repo
        self._security_log = security_log_repo
        self._outbox = outbox_repo
        self._codec = AccessTokenCodec(settings)

    # --- Access tokens -----------------------------------------------

    async def create_access_token(
        self, user: User, session_id: uuid.UUID, *, mfa_verified: bool
    ) -> tuple[str, int]:
        roles_and_role_rows = await self._roles.list_active_user_roles(user.id)
        roles = [role.code for _, role in roles_and_role_rows]
        permissions = sorted(await self._roles.get_effective_permissions(user.id))

        return self._codec.build_and_sign(
            user_id=user.id,
            session_id=session_id,
            roles=roles,
            permissions=permissions,
            email_verified=user.email_verified,
            mobile_verified=user.mobile_verified,
            mfa_verified=mfa_verified,
            token_version=user.token_version,
        )

    def decode_access_token(self, token: str) -> AccessTokenClaims:
        return self._codec.decode(token)

    # --- Refresh tokens / sessions -------------------------------------

    async def issue_session(self, user: User, device: DeviceInfo) -> IssuedSession:
        """Creates a brand-new token family. Called on successful login
        (including the completion of an MFA challenge)."""
        raw_refresh = generate_opaque_token()
        refresh_hash = hash_opaque_token(raw_refresh, self._settings.token_hash_pepper)
        family_id = uuid.uuid4()
        now = datetime.datetime.now(datetime.UTC)
        expire_days = (
            self._settings.refresh_token_remember_expire_days
            if device.remember_me
            else self._settings.refresh_token_expire_days
        )

        session = UserSession(
            user_id=user.id,
            refresh_token_hash=refresh_hash,
            token_family_id=family_id,
            device_id=device.device_id,
            device_name=device.device_name,
            device_platform=device.platform,
            app_version=device.app_version,
            ip_address=device.ip_address,
            user_agent=device.user_agent,
            expires_at=now + datetime.timedelta(days=expire_days),
            last_used_at=now,
        )
        await self._sessions.add(session)

        access_token, expires_in = await self.create_access_token(
            user, session.id, mfa_verified=False
        )
        await self._outbox.enqueue(
            IdentityEvent.SESSION_CREATED,
            {"userId": str(user.id), "sessionId": str(session.id)},
            aggregate_id=user.id,
        )
        return IssuedSession(
            session=session,
            raw_refresh_token=raw_refresh,
            access_token=access_token,
            access_token_expires_in=expires_in,
        )

    async def rotate_refresh_token(
        self, raw_refresh_token: str, device: DeviceInfo
    ) -> IssuedSession:
        """Validates + rotates a refresh token (spec section 9.3), detecting
        reuse of an already-rotated token as probable theft (section 9.4).
        """
        refresh_hash = hash_opaque_token(raw_refresh_token, self._settings.token_hash_pepper)
        existing = await self._sessions.get_by_refresh_hash(refresh_hash)
        if existing is None:
            raise IdentityError.for_code("REFRESH_TOKEN_INVALID")

        now = datetime.datetime.now(datetime.UTC)

        if existing.revoked_at is not None or existing.replaced_by_session_id is not None:
            # The token behind this hash was already rotated away (or
            # explicitly revoked) — presenting it again means it leaked.
            await self._handle_reuse(existing)
            raise IdentityError.for_code("REFRESH_TOKEN_REUSE_DETECTED")

        if existing.expires_at <= now:
            raise IdentityError.for_code("REFRESH_TOKEN_EXPIRED")

        user = await self._users.get_by_id(existing.user_id)
        if user is None:
            raise IdentityError.for_code("REFRESH_TOKEN_INVALID")

        # Rotate: mint the replacement row first, then close out the old one.
        raw_refresh = generate_opaque_token()
        new_hash = hash_opaque_token(raw_refresh, self._settings.token_hash_pepper)
        remaining_lifetime = existing.expires_at - now

        new_session = UserSession(
            user_id=user.id,
            refresh_token_hash=new_hash,
            token_family_id=existing.token_family_id,
            device_id=device.device_id or existing.device_id,
            device_name=device.device_name or existing.device_name,
            device_platform=device.platform or existing.device_platform,
            app_version=device.app_version or existing.app_version,
            ip_address=device.ip_address or existing.ip_address,
            user_agent=device.user_agent or existing.user_agent,
            expires_at=now + remaining_lifetime,
            last_used_at=now,
            parent_session_id=existing.id,
        )
        await self._sessions.add(new_session)

        existing.revoked_at = now
        existing.revoke_reason = "ROTATED"
        existing.replaced_by_session_id = new_session.id

        access_token, expires_in = await self.create_access_token(
            user, new_session.id, mfa_verified=False
        )
        return IssuedSession(
            session=new_session,
            raw_refresh_token=raw_refresh,
            access_token=access_token,
            access_token_expires_in=expires_in,
        )

    async def _handle_reuse(self, session: UserSession) -> None:
        await self._sessions.revoke_family(session.token_family_id, reason="REUSE_DETECTED")

        user = await self._users.get_by_id(session.user_id)
        if user is not None:
            user.token_version += 1

        from app.modules.identity.domain.models import IdentitySecurityEvent

        await self._security_log.add_security_event(
            IdentitySecurityEvent(
                user_id=session.user_id,
                event_type="RefreshTokenReuseDetected",
                severity="CRITICAL",
                session_id=session.id,
                details={"tokenFamilyId": str(session.token_family_id)},
            )
        )
        await self._outbox.enqueue(
            IdentityEvent.REFRESH_TOKEN_REUSED,
            {"userId": str(session.user_id), "tokenFamilyId": str(session.token_family_id)},
            aggregate_id=session.user_id,
        )
