"""Current-user profile management (spec section 17)."""

from __future__ import annotations

import datetime

from app.core.config import Settings
from app.modules.identity.application.normalization import (
    normalize_email,
    try_normalize_mobile_number,
)
from app.modules.identity.application.schemas import UserProfileOut
from app.modules.identity.application.security import (
    PasswordHasher,
    generate_numeric_otp,
    generate_opaque_token,
    hash_opaque_token,
)
from app.modules.identity.domain.enums import AccountStatus, VerificationTokenType
from app.modules.identity.domain.events import IdentityEvent, NotificationCommand
from app.modules.identity.domain.exceptions import IdentityError
from app.modules.identity.domain.models import IdentitySecurityEvent, User, VerificationToken
from app.modules.identity.domain.repositories import (
    OutboxRepository,
    RoleRepository,
    SecurityLogRepository,
    SessionRepository,
    UserRepository,
    VerificationRepository,
)


class UserService:
    def __init__(
        self,
        settings: Settings,
        user_repo: UserRepository,
        role_repo: RoleRepository,
        session_repo: SessionRepository,
        verification_repo: VerificationRepository,
        security_log_repo: SecurityLogRepository,
        outbox_repo: OutboxRepository,
    ) -> None:
        self._settings = settings
        self._users = user_repo
        self._roles = role_repo
        self._sessions = session_repo
        self._verifications = verification_repo
        self._security_log = security_log_repo
        self._outbox = outbox_repo
        self._hasher = PasswordHasher()

    async def get_profile(self, user: User) -> UserProfileOut:
        role_rows = await self._roles.list_active_user_roles(user.id)
        return UserProfileOut(
            id=user.id,
            email=user.email,
            mobile_number=user.mobile_number,
            email_verified=user.email_verified,
            mobile_verified=user.mobile_verified,
            account_status=user.account_status,
            preferred_language=user.preferred_language,
            timezone=user.timezone,
            roles=[role.code for _, role in role_rows],
            created_at=user.created_at,
            last_login_at=user.last_login_at,
        )

    async def update_profile(
        self, user: User, preferred_language: str | None, timezone: str | None
    ) -> None:
        if preferred_language is not None:
            user.preferred_language = preferred_language
        if timezone is not None:
            user.timezone = timezone

    # --- Email change (spec 17.3, 17.4) -----------------------------------

    async def request_email_change(self, user: User, new_email: str, current_password: str) -> None:
        if not self._hasher.verify(current_password, user.password_hash or ""):
            raise IdentityError.for_code("REAUTHENTICATION_REQUIRED")

        normalized = normalize_email(new_email)
        conflict = await self._users.get_by_email(normalized)
        if conflict is not None and conflict.id != user.id:
            raise IdentityError.for_code("EMAIL_ALREADY_REGISTERED")

        await self._verifications.invalidate_active_for_user(
            user.id, VerificationTokenType.EMAIL_CHANGE.value
        )
        raw_token = generate_opaque_token()
        await self._verifications.add(
            VerificationToken(
                user_id=user.id,
                token_type=VerificationTokenType.EMAIL_CHANGE.value,
                token_hash=hash_opaque_token(raw_token, self._settings.token_hash_pepper),
                destination=normalized,
                expires_at=datetime.datetime.now(datetime.UTC)
                + datetime.timedelta(hours=self._settings.email_verification_token_expire_hours),
            )
        )
        confirm_url = f"{self._settings.frontend_base_url}/confirm-email-change?token={raw_token}"
        await self._outbox.enqueue(
            IdentityEvent.EMAIL_VERIFICATION_REQUESTED,
            {
                "notificationCommand": NotificationCommand.EMAIL_VERIFICATION,
                "channel": "EMAIL",
                "destination": normalized,
                "parameters": {"confirmUrl": confirm_url},
            },
            aggregate_id=user.id,
        )

    async def confirm_email_change(self, user: User, raw_token: str) -> None:
        token_hash = hash_opaque_token(raw_token, self._settings.token_hash_pepper)
        token = await self._verifications.get_by_hash(token_hash)
        if (
            token is None
            or token.token_type != VerificationTokenType.EMAIL_CHANGE.value
            or token.user_id != user.id
        ):
            raise IdentityError.for_code("VERIFICATION_TOKEN_INVALID")
        if token.used_at is not None or token.invalidated_at is not None:
            raise IdentityError.for_code("VERIFICATION_TOKEN_USED")
        if token.expires_at <= datetime.datetime.now(datetime.UTC):
            raise IdentityError.for_code("VERIFICATION_TOKEN_EXPIRED")

        old_email = user.email
        token.used_at = datetime.datetime.now(datetime.UTC)
        user.email = token.destination
        user.email_verified = True

        await self._security_log.add_security_event(
            IdentitySecurityEvent(
                user_id=user.id,
                event_type="UserEmailChanged",
                severity="MEDIUM",
                details={"oldEmail": old_email, "newEmail": user.email},
            )
        )
        await self._outbox.enqueue(
            IdentityEvent.USER_EMAIL_CHANGED,
            {
                "userId": str(user.id),
                "notificationCommand": NotificationCommand.EMAIL_CHANGED,
                "channel": "EMAIL",
                "destination": old_email,
                "parameters": {"newEmail": user.email},
            },
            aggregate_id=user.id,
        )

    # --- Mobile change (symmetric with email, OTP-based like mobile verification) --

    async def request_mobile_change(self, user: User, new_mobile_number: str, current_password: str) -> None:
        if not self._hasher.verify(current_password, user.password_hash or ""):
            raise IdentityError.for_code("REAUTHENTICATION_REQUIRED")

        normalized, error = try_normalize_mobile_number(new_mobile_number)
        if error is not None or normalized is None:
            raise IdentityError.for_code("INVALID_MOBILE_FORMAT")

        conflict = await self._users.get_by_mobile(normalized)
        if conflict is not None and conflict.id != user.id:
            raise IdentityError.for_code("MOBILE_ALREADY_REGISTERED")

        await self._verifications.invalidate_active_for_user(
            user.id, VerificationTokenType.MOBILE_CHANGE.value
        )
        raw_otp = generate_numeric_otp(self._settings.mobile_otp_length)
        await self._verifications.add(
            VerificationToken(
                user_id=user.id,
                token_type=VerificationTokenType.MOBILE_CHANGE.value,
                token_hash=hash_opaque_token(raw_otp, self._settings.token_hash_pepper),
                destination=normalized,
                expires_at=datetime.datetime.now(datetime.UTC)
                + datetime.timedelta(minutes=self._settings.mobile_otp_expire_minutes),
                max_attempts=self._settings.mobile_otp_max_attempts,
            )
        )
        await self._outbox.enqueue(
            IdentityEvent.MOBILE_VERIFICATION_REQUESTED,
            {
                "notificationCommand": NotificationCommand.MOBILE_OTP,
                "channel": "SMS",
                "destination": normalized,
                "parameters": {"code": raw_otp, "purpose": "MOBILE_CHANGE"},
            },
            aggregate_id=user.id,
        )

    async def confirm_mobile_change(self, user: User, mobile_number: str, code: str) -> None:
        token = await self._verifications.get_active_for_user(
            user.id, VerificationTokenType.MOBILE_CHANGE.value
        )
        if token is None:
            raise IdentityError.for_code("OTP_EXPIRED")
        if token.expires_at <= datetime.datetime.now(datetime.UTC):
            raise IdentityError.for_code("OTP_EXPIRED")
        if token.destination != mobile_number:
            raise IdentityError.for_code("OTP_INVALID")

        submitted_hash = hash_opaque_token(code, self._settings.token_hash_pepper)
        if submitted_hash != token.token_hash:
            token.attempt_count += 1
            if token.attempt_count >= token.max_attempts:
                token.invalidated_at = datetime.datetime.now(datetime.UTC)
                raise IdentityError.for_code("OTP_MAX_ATTEMPTS_EXCEEDED")
            raise IdentityError.for_code("OTP_INVALID")

        old_mobile = user.mobile_number
        token.used_at = datetime.datetime.now(datetime.UTC)
        user.mobile_number = token.destination
        user.mobile_verified = True

        await self._security_log.add_security_event(
            IdentitySecurityEvent(
                user_id=user.id,
                event_type="UserMobileChanged",
                severity="MEDIUM",
                details={"oldMobile": old_mobile, "newMobile": user.mobile_number},
            )
        )
        await self._outbox.enqueue(
            IdentityEvent.USER_MOBILE_CHANGED, {"userId": str(user.id)}, aggregate_id=user.id
        )

    # --- Deactivation (spec 17.5) -----------------------------------------

    async def deactivate_account(self, user: User, current_password: str) -> None:
        if not self._hasher.verify(current_password, user.password_hash or ""):
            raise IdentityError.for_code("REAUTHENTICATION_REQUIRED")

        user.account_status = AccountStatus.DEACTIVATED.value
        user.token_version += 1
        await self._sessions.revoke_all_for_user(user.id, reason="ACCOUNT_DEACTIVATED")

        await self._security_log.add_security_event(
            IdentitySecurityEvent(user_id=user.id, event_type="UserDeactivated", severity="HIGH")
        )
        await self._outbox.enqueue(
            IdentityEvent.USER_DEACTIVATED, {"userId": str(user.id)}, aggregate_id=user.id
        )
