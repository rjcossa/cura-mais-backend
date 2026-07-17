"""Session listing/revocation (spec section 10)."""

from __future__ import annotations

import uuid

from app.modules.identity.application.schemas import SessionOut
from app.modules.identity.application.security import mask_ip
from app.modules.identity.domain.events import IdentityEvent
from app.modules.identity.domain.exceptions import IdentityError
from app.modules.identity.domain.models import IdentitySecurityEvent
from app.modules.identity.domain.repositories import (
    OutboxRepository,
    SecurityLogRepository,
    SessionRepository,
    UserRepository,
)


class SessionService:
    def __init__(
        self,
        user_repo: UserRepository,
        session_repo: SessionRepository,
        security_log_repo: SecurityLogRepository,
        outbox_repo: OutboxRepository,
    ) -> None:
        self._users = user_repo
        self._sessions = session_repo
        self._security_log = security_log_repo
        self._outbox = outbox_repo

    async def list_sessions(self, user_id: uuid.UUID, current_session_id: uuid.UUID) -> list[SessionOut]:
        heads = await self._sessions.list_active_family_heads(user_id)
        results = []
        for head in heads:
            created_at = await self._sessions.get_family_created_at(head.token_family_id) or head.issued_at
            results.append(
                SessionOut(
                    id=head.id,
                    device_name=head.device_name,
                    platform=head.device_platform,
                    ip_address_masked=mask_ip(head.ip_address),
                    created_at=created_at,
                    last_used_at=head.last_used_at,
                    current=head.id == current_session_id,
                )
            )
        results.sort(key=lambda s: s.created_at, reverse=True)
        return results

    async def revoke_session(
        self, user_id: uuid.UUID, session_id: uuid.UUID, *, revoked_by_admin: uuid.UUID | None = None
    ) -> None:
        session = await self._sessions.get_by_id(session_id)
        if session is None or session.user_id != user_id:
            raise IdentityError.for_code("SESSION_NOT_FOUND")
        if session.revoked_at is not None:
            return  # Idempotent.

        reason = "ADMIN_REVOKED" if revoked_by_admin else "USER_REVOKED"
        await self._sessions.revoke(session, reason)
        await self._security_log.add_security_event(
            IdentitySecurityEvent(
                user_id=user_id,
                event_type="SessionRevoked",
                severity="INFO",
                session_id=session.id,
                details={"revokedByAdmin": str(revoked_by_admin)} if revoked_by_admin else None,
            )
        )
        await self._outbox.enqueue(
            IdentityEvent.SESSION_REVOKED,
            {"userId": str(user_id), "sessionId": str(session_id)},
            aggregate_id=user_id,
        )

    async def logout(self, user_id: uuid.UUID, session_id: uuid.UUID) -> None:
        await self.revoke_session(user_id, session_id)

    async def logout_all(self, user_id: uuid.UUID) -> None:
        user = await self._users.get_by_id(user_id)
        if user is None:
            raise IdentityError.for_code("USER_NOT_FOUND")

        await self._sessions.revoke_all_for_user(user_id, reason="LOGOUT_ALL")
        user.token_version += 1

        await self._security_log.add_security_event(
            IdentitySecurityEvent(user_id=user_id, event_type="AllUserSessionsRevoked", severity="INFO")
        )
        await self._outbox.enqueue(
            IdentityEvent.ALL_USER_SESSIONS_REVOKED, {"userId": str(user_id)}, aggregate_id=user_id
        )
