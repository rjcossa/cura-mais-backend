"""Multi-factor authentication (spec section 15).

Covers authenticator (TOTP) enrolment/confirmation, verifying a login-time
MFA challenge (across AUTHENTICATOR / SMS / EMAIL / RECOVERY_CODE), and
disabling a method with the mandatory-MFA safeguard from section 15.1.

SMS/EMAIL as a *login* second factor: unlike AUTHENTICATOR (which proves
possession of a shared secret the user already has), SMS/EMAIL prove
possession of a code we send at challenge time. Rather than adding new
database tables for this, the one-time code's hash and expiry are stashed
in the MFA_CHALLENGE verification token's `metadata` JSONB column when the
challenge is created (see `AuthenticationService._create_mfa_challenge`
and `issue_secondary_channel_codes` below) and checked from there.
"""

from __future__ import annotations

import datetime
import uuid

import pyotp

from app.core.config import Settings
from app.modules.identity.application.security import (
    MfaSecretCipher,
    PasswordHasher,
    generate_numeric_otp,
    generate_recovery_code,
    hash_opaque_token,
)
from app.modules.identity.application.tokens import DeviceInfo
from app.modules.identity.domain.enums import MANDATORY_MFA_ROLES, MfaMethod, VerificationTokenType
from app.modules.identity.domain.events import IdentityEvent, NotificationCommand
from app.modules.identity.domain.exceptions import IdentityError
from app.modules.identity.domain.models import (
    IdentitySecurityEvent,
    User,
    UserMfaMethod,
    UserRecoveryCode,
    VerificationToken,
)
from app.modules.identity.domain.repositories import (
    MfaRepository,
    OutboxRepository,
    RoleRepository,
    SecurityLogRepository,
    UserRepository,
    VerificationRepository,
)

_OTP_ISSUER = "HealthPlatform"


class MfaService:
    def __init__(
        self,
        settings: Settings,
        user_repo: UserRepository,
        role_repo: RoleRepository,
        mfa_repo: MfaRepository,
        verification_repo: VerificationRepository,
        security_log_repo: SecurityLogRepository,
        outbox_repo: OutboxRepository,
    ) -> None:
        self._settings = settings
        self._users = user_repo
        self._roles = role_repo
        self._mfa = mfa_repo
        self._verifications = verification_repo
        self._security_log = security_log_repo
        self._outbox = outbox_repo
        self._password_hasher = PasswordHasher()
        self._cipher = MfaSecretCipher(settings.mfa_encryption_key)

    # --- Enrolment ------------------------------------------------------

    async def enrol_authenticator(self, user: User) -> tuple[UserMfaMethod, str, str]:
        """Returns (method, raw_secret, otpauth_uri)."""
        secret = pyotp.random_base32()
        method = UserMfaMethod(
            user_id=user.id,
            method=MfaMethod.AUTHENTICATOR.value,
            secret_encrypted=self._cipher.encrypt(secret),
            enabled=False,
            is_primary=False,
        )
        await self._mfa.add_method(method)  # flushes -> populates created_at

        otpauth_uri = pyotp.TOTP(secret).provisioning_uri(
            name=user.email or user.mobile_number or str(user.id), issuer_name=_OTP_ISSUER
        )
        await self._outbox.enqueue(
            IdentityEvent.MFA_ENROLMENT_STARTED, {"userId": str(user.id)}, aggregate_id=user.id
        )
        return method, secret, otpauth_uri

    def enrolment_expires_at(self, method: UserMfaMethod) -> datetime.datetime:
        return method.created_at + datetime.timedelta(minutes=self._settings.mfa_enrolment_expire_minutes)

    async def confirm_authenticator(
        self, user: User, enrolment_id: uuid.UUID, code: str
    ) -> tuple[UserMfaMethod, list[str]]:
        method = await self._mfa.get_method_by_id(enrolment_id)
        if method is None or method.user_id != user.id or method.method != MfaMethod.AUTHENTICATOR.value:
            raise IdentityError.for_code("VERIFICATION_TOKEN_INVALID", "Enrolment not found.")
        if method.enabled:
            raise IdentityError.for_code("VERIFICATION_TOKEN_USED", "This enrolment was already confirmed.")
        if datetime.datetime.now(datetime.UTC) > self.enrolment_expires_at(method):
            raise IdentityError.for_code("MFA_ENROLMENT_EXPIRED")

        secret = self._cipher.decrypt(method.secret_encrypted)
        if not pyotp.TOTP(secret).verify(code, valid_window=1):
            raise IdentityError.for_code("INVALID_MFA_CODE")

        existing_enabled = await self._mfa.list_enabled_methods(user.id)
        method.enabled = True
        method.verified_at = datetime.datetime.now(datetime.UTC)
        method.is_primary = len(existing_enabled) == 0

        raw_codes = await self._issue_recovery_codes(user.id)

        await self._security_log.add_security_event(
            IdentitySecurityEvent(user_id=user.id, event_type="MfaEnabled", severity="INFO")
        )
        await self._outbox.enqueue(
            IdentityEvent.MFA_ENABLED,
            {
                "userId": str(user.id),
                "method": MfaMethod.AUTHENTICATOR.value,
                "notificationCommand": NotificationCommand.MFA_ENABLED,
                "channel": "EMAIL",
                "destination": user.email,
                "parameters": {},
            },
            aggregate_id=user.id,
        )
        return method, raw_codes

    async def _issue_recovery_codes(self, user_id: uuid.UUID) -> list[str]:
        await self._mfa.invalidate_unused_recovery_codes(user_id)
        raw_codes = [generate_recovery_code() for _ in range(self._settings.recovery_codes_count)]
        rows = [
            UserRecoveryCode(
                user_id=user_id,
                code_hash=hash_opaque_token(code, self._settings.token_hash_pepper),
            )
            for code in raw_codes
        ]
        await self._mfa.add_recovery_codes(rows)
        return raw_codes

    async def regenerate_recovery_codes(self, user: User, current_password: str) -> list[str]:
        if not self._password_hasher.verify(current_password, user.password_hash or ""):
            raise IdentityError.for_code("REAUTHENTICATION_REQUIRED")
        return await self._issue_recovery_codes(user.id)

    # --- Login-time challenge --------------------------------------------

    async def issue_secondary_channel_codes(
        self, user: User, enabled_methods: list[UserMfaMethod]
    ) -> dict:
        """Called when a login MFA challenge is created. For any enabled
        SMS/EMAIL method, generates + "sends" (via outbox) a one-time code
        and returns the metadata to embed in the challenge token so it can
        be checked later without a second database table.
        """
        metadata: dict = {}
        now = datetime.datetime.now(datetime.UTC)
        expires_at = now + datetime.timedelta(minutes=self._settings.mfa_challenge_expire_minutes)

        for method in enabled_methods:
            if method.method == MfaMethod.SMS.value and user.mobile_number:
                raw = generate_numeric_otp(self._settings.mobile_otp_length)
                metadata["smsOtpHash"] = hash_opaque_token(raw, self._settings.token_hash_pepper)
                metadata["smsOtpExpiresAt"] = expires_at.isoformat()
                await self._outbox.enqueue(
                    IdentityEvent.MOBILE_VERIFICATION_REQUESTED,
                    {
                        "notificationCommand": NotificationCommand.MOBILE_OTP,
                        "channel": "SMS",
                        "destination": user.mobile_number,
                        "parameters": {"code": raw, "purpose": "MFA_LOGIN"},
                    },
                    aggregate_id=user.id,
                )
            elif method.method == MfaMethod.EMAIL.value and user.email:
                raw = generate_numeric_otp(self._settings.mobile_otp_length)
                metadata["emailOtpHash"] = hash_opaque_token(raw, self._settings.token_hash_pepper)
                metadata["emailOtpExpiresAt"] = expires_at.isoformat()
                await self._outbox.enqueue(
                    IdentityEvent.EMAIL_VERIFICATION_REQUESTED,
                    {
                        "notificationCommand": NotificationCommand.MOBILE_OTP,
                        "channel": "EMAIL",
                        "destination": user.email,
                        "parameters": {"code": raw, "purpose": "MFA_LOGIN"},
                    },
                    aggregate_id=user.id,
                )
        return metadata

    async def create_login_challenge(self, user: User, device: DeviceInfo) -> VerificationToken:
        """Shared by password login and social login (spec 14.4 "Apply MFA
        policy") — builds the MFA_CHALLENGE token, embedding secondary
        channel (SMS/EMAIL) one-time codes and device info needed to
        finish issuing a session once the challenge is satisfied.
        """
        enabled_methods = await self._mfa.list_enabled_methods(user.id)
        expires_at = datetime.datetime.now(datetime.UTC) + datetime.timedelta(
            minutes=self._settings.mfa_challenge_expire_minutes
        )
        challenge_secret = hash_opaque_token(str(uuid.uuid4()), self._settings.token_hash_pepper)
        metadata = {
            "deviceId": device.device_id,
            "deviceName": device.device_name,
            "platform": device.platform,
            "appVersion": device.app_version,
            "rememberMe": device.remember_me,
        }
        metadata.update(await self.issue_secondary_channel_codes(user, enabled_methods))

        token = VerificationToken(
            user_id=user.id,
            token_type=VerificationTokenType.MFA_CHALLENGE.value,
            token_hash=challenge_secret,
            expires_at=expires_at,
            token_metadata=metadata,
        )
        await self._verifications.add(token)
        return token

    async def verify_login_challenge(
        self, challenge_id: uuid.UUID, method: str, code: str
    ) -> tuple[User, DeviceInfo]:
        token = await self._verifications.get_by_id(challenge_id)
        if (
            token is None
            or token.token_type != "MFA_CHALLENGE"
            or token.used_at is not None
            or token.invalidated_at is not None
        ):
            raise IdentityError.for_code("MFA_CHALLENGE_EXPIRED")
        if token.expires_at <= datetime.datetime.now(datetime.UTC):
            raise IdentityError.for_code("MFA_CHALLENGE_EXPIRED")

        user = await self._users.get_by_id(token.user_id)
        if user is None:
            raise IdentityError.for_code("MFA_CHALLENGE_EXPIRED")

        ok = await self._check_code(user, method, code, token.token_metadata or {})
        if not ok:
            token.attempt_count += 1
            if token.attempt_count >= token.max_attempts:
                token.invalidated_at = datetime.datetime.now(datetime.UTC)
            raise IdentityError.for_code("INVALID_MFA_CODE")

        token.used_at = datetime.datetime.now(datetime.UTC)

        meta = token.token_metadata or {}
        device = DeviceInfo(
            device_id=meta.get("deviceId"),
            device_name=meta.get("deviceName"),
            platform=meta.get("platform"),
            app_version=meta.get("appVersion"),
            remember_me=bool(meta.get("rememberMe", False)),
        )
        return user, device

    async def _check_code(self, user: User, method: str, code: str, metadata: dict) -> bool:
        if method == "RECOVERY_CODE":
            code_hash = hash_opaque_token(code.strip().upper(), self._settings.token_hash_pepper)
            recovery = await self._mfa.get_recovery_code_by_hash(user.id, code_hash)
            if recovery is None:
                return False
            recovery.used_at = datetime.datetime.now(datetime.UTC)
            await self._security_log.add_security_event(
                IdentitySecurityEvent(user_id=user.id, event_type="RecoveryCodeUsed", severity="HIGH")
            )
            await self._outbox.enqueue(
                IdentityEvent.RECOVERY_CODE_USED, {"userId": str(user.id)}, aggregate_id=user.id
            )
            return True

        if method == MfaMethod.AUTHENTICATOR.value:
            methods = await self._mfa.list_enabled_methods(user.id)
            authenticator = next((m for m in methods if m.method == MfaMethod.AUTHENTICATOR.value), None)
            if authenticator is None or not authenticator.secret_encrypted:
                return False
            secret = self._cipher.decrypt(authenticator.secret_encrypted)
            return pyotp.TOTP(secret).verify(code, valid_window=1)

        if method == MfaMethod.SMS.value:
            expected_hash = metadata.get("smsOtpHash")
            expires_at = metadata.get("smsOtpExpiresAt")
            return self._check_channel_code(code, expected_hash, expires_at)

        if method == MfaMethod.EMAIL.value:
            expected_hash = metadata.get("emailOtpHash")
            expires_at = metadata.get("emailOtpExpiresAt")
            return self._check_channel_code(code, expected_hash, expires_at)

        return False

    def _check_channel_code(self, code: str, expected_hash: str | None, expires_at: str | None) -> bool:
        if not expected_hash or not expires_at:
            return False
        if datetime.datetime.fromisoformat(expires_at) <= datetime.datetime.now(datetime.UTC):
            return False
        return hash_opaque_token(code, self._settings.token_hash_pepper) == expected_hash

    # --- Disable ----------------------------------------------------------

    async def disable_mfa(self, user: User, method_id: uuid.UUID, current_password: str) -> None:
        if not self._password_hasher.verify(current_password, user.password_hash or ""):
            raise IdentityError.for_code("REAUTHENTICATION_REQUIRED")

        method = await self._mfa.get_method_by_id(method_id)
        if method is None or method.user_id != user.id or not method.enabled:
            raise IdentityError.for_code("VERIFICATION_TOKEN_INVALID", "MFA method not found.")

        user_role_rows = await self._roles.list_active_user_roles(user.id)
        has_mandatory_role = any(
            role.code in {r.value for r in MANDATORY_MFA_ROLES} for _, role in user_role_rows
        )
        if has_mandatory_role:
            remaining = await self._mfa.list_enabled_methods(user.id)
            if len(remaining) <= 1:
                raise IdentityError.for_code("MANDATORY_MFA_REQUIRED")

        method.enabled = False
        method.disabled_at = datetime.datetime.now(datetime.UTC)

        await self._security_log.add_security_event(
            IdentitySecurityEvent(user_id=user.id, event_type="MfaDisabled", severity="MEDIUM")
        )
        await self._outbox.enqueue(
            IdentityEvent.MFA_DISABLED,
            {
                "userId": str(user.id),
                "method": method.method,
                "notificationCommand": NotificationCommand.MFA_DISABLED,
                "channel": "EMAIL",
                "destination": user.email,
                "parameters": {},
            },
            aggregate_id=user.id,
        )
