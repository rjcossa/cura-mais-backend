"""Provider module port (Onboarding spec section 21.4) and a mock adapter.

The real Provider module now exists (`app.modules.providers`) and
satisfies this port for real via
`app.modules.providers.infrastructure.provider_port_adapter.ProviderPortAdapter`
— constructed directly at each call site (Identity's and Onboarding's own
outbox dispatchers), the same way those dispatchers already build
`IdentityAdapter`/`RoleService` fresh per delivery, rather than through
this module's `get_provider_adapter()` singleton. That singleton (and
`MockProviderAdapter`) stay as-is, still used by tests that want a pure
in-memory stand-in and by anything that hasn't been wired to the real
adapter. The mock's `validate_provider_profile` always returns True — no
call site actually depends on it today (confirmed by inspection), so it
stays a placeholder for a future consumer rather than real validation
logic.

`create_provider` (spec 8.1's provider-creation flow) was added to the
Protocol/mock alongside the real module — the ID parameter across every
method here is the Identity **user_id**, not a hypothetical `providers.id`
(confirmed by reading how Onboarding's `application_service.py` derives
`applicant_entity_id` for DOCTOR/NUTRITIONIST applicants: it's set to
`applicant_user_id` directly).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Protocol


@dataclass(slots=True)
class ProviderProfile:
    provider_id: uuid.UUID
    exists: bool
    active: bool = False
    approval_reference: str | None = None


@dataclass(slots=True)
class ProviderActivationCall:
    provider_id: uuid.UUID
    action: str  # ACTIVATE | SUSPEND | REINSTATE
    reference_or_reason: str | None


class ProviderPort(Protocol):
    async def create_provider(
        self, user_id: uuid.UUID, *, provider_type: str, first_name: str, last_name: str, email: str | None = None
    ) -> None: ...
    async def get_provider_profile(self, provider_id: uuid.UUID) -> ProviderProfile: ...
    async def validate_provider_profile(self, provider_id: uuid.UUID) -> bool: ...
    async def activate_provider(self, provider_id: uuid.UUID, *, approval_reference: str) -> None: ...
    async def suspend_provider(self, provider_id: uuid.UUID, *, reason: str) -> None: ...
    async def reinstate_provider(self, provider_id: uuid.UUID, *, approval_reference: str) -> None: ...


class MockProviderAdapter:
    """Records activation/suspension calls in memory so tests and
    developers can verify Onboarding called through correctly, without a
    real Provider module to call into yet.
    """

    def __init__(self) -> None:
        self.calls: list[ProviderActivationCall] = []
        self._active: dict[uuid.UUID, bool] = {}
        self.created: list[uuid.UUID] = []

    async def create_provider(
        self, user_id: uuid.UUID, *, provider_type: str, first_name: str, last_name: str, email: str | None = None
    ) -> None:
        self.created.append(user_id)

    async def get_provider_profile(self, provider_id: uuid.UUID) -> ProviderProfile:
        return ProviderProfile(provider_id=provider_id, exists=True, active=self._active.get(provider_id, False))

    async def validate_provider_profile(self, provider_id: uuid.UUID) -> bool:
        return True  # No real profile to validate against yet.

    async def activate_provider(self, provider_id: uuid.UUID, *, approval_reference: str) -> None:
        self._active[provider_id] = True
        self.calls.append(ProviderActivationCall(provider_id, "ACTIVATE", approval_reference))

    async def suspend_provider(self, provider_id: uuid.UUID, *, reason: str) -> None:
        self._active[provider_id] = False
        self.calls.append(ProviderActivationCall(provider_id, "SUSPEND", reason))

    async def reinstate_provider(self, provider_id: uuid.UUID, *, approval_reference: str) -> None:
        self._active[provider_id] = True
        self.calls.append(ProviderActivationCall(provider_id, "REINSTATE", approval_reference))


_adapter: MockProviderAdapter | None = None


def get_provider_adapter() -> ProviderPort:
    global _adapter
    if _adapter is None:
        _adapter = MockProviderAdapter()
    return _adapter
