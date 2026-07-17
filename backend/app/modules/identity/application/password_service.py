"""Password change / forgot / reset (spec section 13)."""

from __future__ import annotations

import datetime

from app.core.config import Settings
from app.modules.identity.application.normalization import normalize_email
from app.modules.identity.application.security import (
    PasswordHasher,
    PasswordPolicy,
    generate_opaque_token,
    hash_opaque_token,
)
from app.modules.identity.domain.enums import VerificationTokenType
from app.modules.identity.domain.events import IdentityEvent, NotificationCommand
from app.modules.identity.domain.exceptions import IdentityError
from app.modules.identity.domain.models import (
    IdentitySecurityEvent,
    PasswordHistory,
    User,
    VerificationToken,
)
from app.modules.identity.domain.repositories import (
    OutboxRepository,
    SecurityLogRepository,
    SessionRepository,
    UserRepository,
    VerificationRepository,
)


class PasswordService:
    def __init__(
        self,
        settings: Settings,
        user_repo: UserRepository,
        session_repo: SessionRepository,
        verification_repo: VerificationRepository,
        security_log_repo: SecurityLogRepository,
        outbox_repo: OutboxRepository,
    ) -> None:
        self._settings = settings
        self._users = user_repo
        self._sessions = session_repo
        self._verifications = verification_repo
        self._security_log = security_log_repo
        self._outbox = outbox_repo
        self._hasher = PasswordHasher()
        self._policy = PasswordPolicy(
            min_length=settings.password_min_length, max_length=settings.password_max_length
        )

    async def change_password(
        self, user: User, current_password: str, new_password: str, current_session_id
    ) -> None:
        if not self._hasher.verify(current_password, user.password_hash or ""):
            raise IdentityError.for_code("CURRENT_PASSWORD_INCORRECT")
        if self._hasher.verify(new_password, user.password_hash or ""):
            raise IdentityError.for_code("NEW_PASSWORD_SAME_AS_CURRENT")

        await self._apply_new_password(user, new_password, keep_session_id=current_session_id)
        await self._security_log.add_security_event(
            IdentitySecurityEvent(user_id=user.id, event_type="PasswordChanged", severity="MEDIUM")
        )
        await self._outbox.enqueue(
            IdentityEvent.PASSWORD_CHANGED,
            {
                "userId": str(user.id),
                "notificationCommand": NotificationCommand.PASSWORD_CHANGED,
                "channel": "EMAIL",
                "destination": user.email,
                "parameters": {},
            },
            aggregate_id=user.id,
        )

    async def forgot_password(self, email: str) -> None:
        user = await self._users.get_by_email(normalize_email(email))
        if user is None:
            return  # Generic response; no account-existence disclosure.

        await self._verifications.invalidate_active_for_user(
            user.id, VerificationTokenType.PASSWORD_RESET.value
        )
        raw_token = generate_opaque_token()
        token_hash = hash_opaque_token(raw_token, self._settings.token_hash_pepper)
        await self._verifications.add(
            VerificationToken(
                user_id=user.id,
                token_type=VerificationTokenType.PASSWORD_RESET.value,
                token_hash=token_hash,
                expires_at=datetime.datetime.now(datetime.UTC)
                + datetime.timedelta(minutes=self._settings.password_reset_token_expire_minutes),
            )
        )
        reset_url = f"{self._settings.frontend_base_url}/reset-password?token={raw_token}"
        await self._outbox.enqueue(
            IdentityEvent.PASSWORD_RESET_REQUESTED,
            {
                "notificationCommand": NotificationCommand.PASSWORD_RESET,
                "channel": "EMAIL",
                "destination": user.email,
                "parameters": {"resetUrl": reset_url},
            },
            aggregate_id=user.id,
        )

    async def reset_password(self, raw_token: str, new_password: str) -> None:
        token_hash = hash_opaque_token(raw_token, self._settings.token_hash_pepper)
        token = await self._verifications.get_by_hash(token_hash)
        if token is None or token.token_type != VerificationTokenType.PASSWORD_RESET.value:
            raise IdentityError.for_code("PASSWORD_RESET_TOKEN_INVALID")
        if token.used_at is not None or token.invalidated_at is not None:
            raise IdentityError.for_code("PASSWORD_RESET_TOKEN_INVALID")
        if token.expires_at <= datetime.datetime.now(datetime.UTC):
            raise IdentityError.for_code("PASSWORD_RESET_TOKEN_EXPIRED")

        user = await self._users.get_by_id(token.user_id)
        if user is None:
            raise IdentityError.for_code("PASSWORD_RESET_TOKEN_INVALID")

        token.used_at = datetime.datetime.now(datetime.UTC)
        await self._apply_new_password(user, new_password, keep_session_id=None)

        await self._security_log.add_security_event(
            IdentitySecurityEvent(user_id=user.id, event_type="PasswordChanged", severity="HIGH")
        )
        await self._outbox.enqueue(
            IdentityEvent.PASSWORD_CHANGED,
            {
                "userId": str(user.id),
                "notificationCommand": NotificationCommand.PASSWORD_CHANGED,
                "channel": "EMAIL",
                "destination": user.email,
                "parameters": {"viaReset": True},
            },
            aggregate_id=user.id,
        )

    async def _apply_new_password(
        self, user: User, new_password: str, *, keep_session_id=None
    ) -> None:
        errors = self._policy.validate(new_password, email=user.email)
        if errors:
            raise IdentityError.for_code(
                "PASSWORD_POLICY_VIOLATION", fields=errors
            )

        recent_hashes = await self._users.list_recent_password_hashes(
            user.id, self._settings.password_history_size
        )
        if any(self._hasher.verify(new_password, h) for h in recent_hashes):
            raise IdentityError.for_code("PASSWORD_PREVIOUSLY_USED")

        if user.password_hash:
            await self._users.add_password_history(
                PasswordHistory(user_id=user.id, password_hash=user.password_hash)
            )

        user.password_hash = self._hasher.hash(new_password)
        user.password_changed_at = datetime.datetime.now(datetime.UTC)
        user.token_version += 1

        if keep_session_id is not None:
            await self._sessions.revoke_all_for_user_except(
                user.id, keep_session_id, reason="PASSWORD_CHANGED"
            )
        else:
            await self._sessions.revoke_all_for_user(user.id, reason="PASSWORD_CHANGED")
