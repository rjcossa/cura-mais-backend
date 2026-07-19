"""Identity module integration (spec section 24) — read-only. Providers
never assigns/revokes roles itself ("The Providers module must not assign
roles directly through database access" — role transitions on approval
are Onboarding's job, via its own `identity_adapter.py`). Same wrapping
approach as `app.modules.onboarding.infrastructure.identity_adapter`.
"""

from __future__ import annotations

import uuid
from typing import Protocol

from app.modules.identity.application.identity_ports import IdentityQueryService


class IdentityPort(Protocol):
    async def is_user_active(self, user_id: uuid.UUID) -> bool: ...
    async def has_role(self, user_id: uuid.UUID, role_code: str) -> bool: ...


class IdentityAdapter:
    def __init__(self, query_service: IdentityQueryService) -> None:
        self._query = query_service

    async def is_user_active(self, user_id: uuid.UUID) -> bool:
        return await self._query.is_user_active(user_id)

    async def has_role(self, user_id: uuid.UUID, role_code: str) -> bool:
        return await self._query.has_role(user_id, role_code)
