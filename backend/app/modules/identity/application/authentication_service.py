"""Login orchestration (spec section 7).

Deliberately thin: password verification and lockout live here; the actual
TOTP/SMS/recovery-code check for a login MFA challenge is delegated to
`MfaService` (spec section 15), and token/session issuance is delegated to
`TokenService` (spec sections 8-9). This service's job is to sequence
those two and apply the account-status/lockout rules from section 7.2.
"""

from __future__ import annotations

import datetime
import uuid

from app.core.config import Settings
from app.modules.identity.application.mfa_service import MfaService
from app.modules.identity.application.normalization import normalize_email
from app.modules.identity.application.schemas import (
    DeviceInfoIn,
    LoginSuccessResponse,
    MfaRequiredResponse,
)
from app.modules.identity.application.security import PasswordHasher, hash_opaque_token
from app.modules.identity.application.tokens import DeviceInfo, TokenService
from app.modules.identity.domain.enums import AccountStatus
from app.modules.identity.domain.events import IdentityEvent
from app.modules.identity.domain.exceptions import IdentityError
from app.modules.identity.domain.models import IdentitySecurityEvent, LoginAttempt, User
from app.modules.identity.domain.repositories import (
    MfaRepository,
    OutboxRepository,
    SecurityLogRepository,
    UserRepository,
)


def _to_device(device_in: DeviceInfoIn, ip_address: str | None, user_agent: str | None) -> DeviceInfo:
    return DeviceInfo(
        device_id=device_in.device_id,
        device_name=device_in.device_name,
        platform=device_in.platform,
        app_version=device_in.app_version,
        ip_address=ip_address,
        user_agent=user_agent,
        remember_me=device_in.remember_me,
    )


class AuthenticationService:
    def __init__(
        self,
        settings: Settings,
        user_repo: UserRepository,
        mfa_repo: MfaRepository,
        security_log_repo: SecurityLogRepository,
        outbox_repo: OutboxRepository,
        token_service: TokenService,
        mfa_service: MfaService,
    ) -> None:
        self._settings = settings
        self._users = user_repo
        self._mfa = mfa_repo
        self._security_log = security_log_repo
        self._outbox = outbox_repo
        self._tokens = token_service
        self._mfa_service = mfa_service
        self._password_hasher = PasswordHasher()

    async def login(
        self,
        email: str,
        password: str,
        device_in: DeviceInfoIn,
        *,
        ip_address: str | None,
        user_agent: str | None,
    ) -> LoginSuccessResponse | MfaRequiredResponse:
        normalized_email = normalize_email(email)
        identifier_hash = hash_opaque_token(normalized_email, self._settings.token_hash_pepper)
        device = _to_device(device_in, ip_address, user_agent)

        user = await self._users.get_by_email(normalized_email)
        if user is None:
            await self._record_attempt(None, identifier_hash, "FAILURE", "UNKNOWN_ACCOUNT", device)
            raise IdentityError.for_code("INVALID_CREDENTIALS")

        # Hard-fail statuses: skip password verification entirely.
        if user.account_status == AccountStatus.SUSPENDED.value:
            await self._record_attempt(user.id, identifier_hash, "BLOCKED", "ACCOUNT_SUSPENDED", device)
            raise IdentityError.for_code("ACCOUNT_SUSPENDED")
        if user.account_status == AccountStatus.DEACTIVATED.value:
            await self._record_attempt(user.id, identifier_hash, "BLOCKED", "ACCOUNT_DEACTIVATED", device)
            raise IdentityError.for_code("ACCOUNT_DEACTIVATED")
        if user.account_status == AccountStatus.DELETED.value:
            await self._record_attempt(user.id, identifier_hash, "FAILURE", "UNKNOWN_ACCOUNT", device)
            raise IdentityError.for_code("INVALID_CREDENTIALS")

        now = datetime.datetime.now(datetime.UTC)
        if user.account_status == AccountStatus.LOCKED.value:
            if user.locked_until is not None and user.locked_until > now:
                await self._record_attempt(user.id, identifier_hash, "BLOCKED", "ACCOUNT_LOCKED", device)
                raise IdentityError.for_code("ACCOUNT_LOCKED")
            # Lock has expired: clear it and fall through to a normal attempt.
            user.account_status = AccountStatus.ACTIVE.value
            user.locked_until = None
            user.failed_login_attempts = 0

        if not self._password_hasher.verify(password, user.password_hash or ""):
            await self._handle_failed_password(user, identifier_hash, device)
            raise IdentityError.for_code("INVALID_CREDENTIALS")

        if self._password_hasher.needs_rehash(user.password_hash or ""):
            user.password_hash = self._password_hasher.hash(password)

        # NOTE: per spec section 5.1, PENDING_VERIFICATION accounts may
        # "log in with limited access where explicitly supported" — this
        # deployment treats verification as gating specific actions (e.g.
        # purchasing prescription medicine) downstream rather than gating
        # login itself. Flip `require_email_verification_to_login` if a
        # stricter policy is wanted; the ACCOUNT_NOT_VERIFIED error code and
        # its test coverage are ready either way.
        if self._settings.require_email_verification_to_login and not user.email_verified:
            await self._record_attempt(user.id, identifier_hash, "BLOCKED", "ACCOUNT_NOT_VERIFIED", device)
            raise IdentityError.for_code("ACCOUNT_NOT_VERIFIED")

        user.failed_login_attempts = 0

        enabled_methods = await self._mfa.list_enabled_methods(user.id)
        if enabled_methods:
            challenge = await self._mfa_service.create_login_challenge(user, device)
            await self._record_attempt(user.id, identifier_hash, "MFA_REQUIRED", None, device)
            return MfaRequiredResponse(
                challenge_id=challenge.id,
                methods=sorted({m.method for m in enabled_methods}),
            )

        issued = await self._tokens.issue_session(user, device)
        user.last_login_at = now
        await self._record_attempt(user.id, identifier_hash, "SUCCESS", None, device)
        await self._outbox.enqueue(
            IdentityEvent.USER_LOGGED_IN,
            {"userId": str(user.id), "sessionId": str(issued.session.id)},
            aggregate_id=user.id,
        )
        return LoginSuccessResponse(
            access_token=issued.access_token,
            refresh_token=issued.raw_refresh_token,
            expires_in=issued.access_token_expires_in,
            mfa_required=False,
        )

    async def complete_mfa_login(
        self,
        challenge_id: uuid.UUID,
        method: str,
        code: str,
        *,
        ip_address: str | None,
        user_agent: str | None,
    ) -> LoginSuccessResponse:
        user, device = await self._mfa_service.verify_login_challenge(challenge_id, method, code)
        if device.ip_address is None:
            device.ip_address = ip_address
        if device.user_agent is None:
            device.user_agent = user_agent

        issued = await self._tokens.issue_session(user, device)
        # Re-issue the access token with mfa_verified=True now that the
        # challenge has been satisfied for this login.
        access_token, expires_in = await self._tokens.create_access_token(
            user, issued.session.id, mfa_verified=True
        )
        user.last_login_at = datetime.datetime.now(datetime.UTC)

        await self._outbox.enqueue(
            IdentityEvent.USER_LOGGED_IN,
            {"userId": str(user.id), "sessionId": str(issued.session.id), "mfa": True},
            aggregate_id=user.id,
        )
        return LoginSuccessResponse(
            access_token=access_token,
            refresh_token=issued.raw_refresh_token,
            expires_in=expires_in,
            mfa_required=False,
        )

    async def _handle_failed_password(
        self, user: User, identifier_hash: str, device: DeviceInfo
    ) -> None:
        user.failed_login_attempts += 1
        await self._record_attempt(user.id, identifier_hash, "FAILURE", "INVALID_PASSWORD", device)

        if user.failed_login_attempts >= self._settings.failed_login_attempts_before_lock:
            user.account_status = AccountStatus.LOCKED.value
            user.locked_until = datetime.datetime.now(datetime.UTC) + datetime.timedelta(
                minutes=self._settings.account_lock_duration_minutes
            )
            await self._security_log.add_security_event(
                IdentitySecurityEvent(
                    user_id=user.id,
                    event_type="AccountTemporarilyLocked",
                    severity="MEDIUM",
                    ip_address=device.ip_address,
                    user_agent=device.user_agent,
                    device_id=device.device_id,
                )
            )
            await self._outbox.enqueue(
                IdentityEvent.ACCOUNT_TEMPORARILY_LOCKED,
                {"userId": str(user.id), "lockedUntil": user.locked_until.isoformat()},
                aggregate_id=user.id,
            )

    async def _record_attempt(
        self,
        user_id: uuid.UUID | None,
        identifier_hash: str,
        outcome: str,
        failure_reason: str | None,
        device: DeviceInfo,
    ) -> None:
        await self._security_log.add_login_attempt(
            LoginAttempt(
                user_id=user_id,
                identifier_hash=identifier_hash,
                identifier_type="EMAIL",
                outcome=outcome,
                failure_reason=failure_reason,
                ip_address=device.ip_address,
                user_agent=device.user_agent,
                device_id=device.device_id,
            )
        )
