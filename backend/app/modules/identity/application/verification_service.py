"""Email verification and mobile OTP verification (spec sections 11-12)."""

from __future__ import annotations

import datetime

from app.core.config import Settings
from app.modules.identity.application.normalization import (
    normalize_email,
    try_normalize_mobile_number,
)
from app.modules.identity.application.security import (
    generate_numeric_otp,
    generate_opaque_token,
    hash_opaque_token,
)
from app.modules.identity.domain.enums import AccountStatus, VerificationTokenType
from app.modules.identity.domain.events import IdentityEvent, NotificationCommand
from app.modules.identity.domain.exceptions import IdentityError
from app.modules.identity.domain.models import VerificationToken
from app.modules.identity.domain.repositories import (
    OutboxRepository,
    UserRepository,
    VerificationRepository,
)


class VerificationService:
    def __init__(
        self,
        settings: Settings,
        user_repo: UserRepository,
        verification_repo: VerificationRepository,
        outbox_repo: OutboxRepository,
    ) -> None:
        self._settings = settings
        self._users = user_repo
        self._verifications = verification_repo
        self._outbox = outbox_repo

    # --- Email -------------------------------------------------------

    async def resend_email_verification(self, email: str) -> None:
        """Always succeeds from the caller's perspective (spec 11.1: "The
        endpoint must always return a generic response")."""
        user = await self._users.get_by_email(normalize_email(email))
        if user is None or user.email_verified:
            return

        await self._verifications.invalidate_active_for_user(
            user.id, VerificationTokenType.EMAIL_VERIFICATION.value
        )
        raw_token = generate_opaque_token()
        token_hash = hash_opaque_token(raw_token, self._settings.token_hash_pepper)
        await self._verifications.add(
            VerificationToken(
                user_id=user.id,
                token_type=VerificationTokenType.EMAIL_VERIFICATION.value,
                token_hash=token_hash,
                expires_at=datetime.datetime.now(datetime.UTC)
                + datetime.timedelta(hours=self._settings.email_verification_token_expire_hours),
            )
        )
        verification_url = f"{self._settings.frontend_base_url}/verify-email?token={raw_token}"
        await self._outbox.enqueue(
            IdentityEvent.EMAIL_VERIFICATION_REQUESTED,
            {
                "notificationCommand": NotificationCommand.EMAIL_VERIFICATION,
                "channel": "EMAIL",
                "destination": user.email,
                "parameters": {"verificationUrl": verification_url},
            },
            aggregate_id=user.id,
        )

    async def verify_email(self, raw_token: str) -> None:
        token_hash = hash_opaque_token(raw_token, self._settings.token_hash_pepper)
        token = await self._verifications.get_by_hash(token_hash)
        if token is None or token.token_type != VerificationTokenType.EMAIL_VERIFICATION.value:
            raise IdentityError.for_code("VERIFICATION_TOKEN_INVALID")
        if token.used_at is not None or token.invalidated_at is not None:
            raise IdentityError.for_code("VERIFICATION_TOKEN_USED")
        if token.expires_at <= datetime.datetime.now(datetime.UTC):
            raise IdentityError.for_code("VERIFICATION_TOKEN_EXPIRED")

        user = await self._users.get_by_id(token.user_id)
        if user is None:
            raise IdentityError.for_code("VERIFICATION_TOKEN_INVALID")

        token.used_at = datetime.datetime.now(datetime.UTC)
        user.email_verified = True
        self._activate_if_fully_verified(user)

        await self._outbox.enqueue(
            IdentityEvent.EMAIL_VERIFIED, {"userId": str(user.id)}, aggregate_id=user.id
        )

    # --- Mobile --------------------------------------------------------

    async def send_mobile_otp(self, mobile_number: str, purpose: str = "MOBILE_VERIFICATION") -> None:
        normalized, error = try_normalize_mobile_number(mobile_number)
        if error is not None or normalized is None:
            return  # Generic response; do not confirm format validity of a non-existent number.

        user = await self._users.get_by_mobile(normalized)
        if user is None:
            return
        if purpose == "MOBILE_VERIFICATION" and user.mobile_verified:
            return

        await self._verifications.invalidate_active_for_user(
            user.id, VerificationTokenType.MOBILE_OTP.value
        )
        raw_otp = generate_numeric_otp(self._settings.mobile_otp_length)
        otp_hash = hash_opaque_token(raw_otp, self._settings.token_hash_pepper)
        await self._verifications.add(
            VerificationToken(
                user_id=user.id,
                token_type=VerificationTokenType.MOBILE_OTP.value,
                token_hash=otp_hash,
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
                "parameters": {"code": raw_otp, "purpose": purpose},
            },
            aggregate_id=user.id,
        )

    async def verify_mobile_otp(
        self, mobile_number: str, code: str, purpose: str = "MOBILE_VERIFICATION"
    ) -> None:
        normalized, error = try_normalize_mobile_number(mobile_number)
        if error is not None or normalized is None:
            raise IdentityError.for_code("OTP_INVALID")

        user = await self._users.get_by_mobile(normalized)
        if user is None:
            raise IdentityError.for_code("OTP_INVALID")

        token = await self._verifications.get_active_for_user(
            user.id, VerificationTokenType.MOBILE_OTP.value
        )
        if token is None:
            raise IdentityError.for_code("OTP_EXPIRED")
        if token.expires_at <= datetime.datetime.now(datetime.UTC):
            raise IdentityError.for_code("OTP_EXPIRED")

        submitted_hash = hash_opaque_token(code, self._settings.token_hash_pepper)
        if submitted_hash != token.token_hash:
            token.attempt_count += 1
            if token.attempt_count >= token.max_attempts:
                token.invalidated_at = datetime.datetime.now(datetime.UTC)
                raise IdentityError.for_code("OTP_MAX_ATTEMPTS_EXCEEDED")
            raise IdentityError.for_code("OTP_INVALID")

        token.used_at = datetime.datetime.now(datetime.UTC)
        user.mobile_verified = True
        self._activate_if_fully_verified(user)

        await self._outbox.enqueue(
            IdentityEvent.MOBILE_VERIFIED, {"userId": str(user.id)}, aggregate_id=user.id
        )

    @staticmethod
    def _activate_if_fully_verified(user) -> None:
        if (
            user.account_status == AccountStatus.PENDING_VERIFICATION.value
            and user.email_verified
            and user.mobile_verified
        ):
            user.account_status = AccountStatus.ACTIVE.value
