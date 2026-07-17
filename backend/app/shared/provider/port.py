"""Provider module port (Onboarding spec section 21.4) and a mock adapter.

The Provider module (doctor/nutritionist public profiles, availability,
consultation pricing, etc.) doesn't exist yet. Same pattern as
`app/shared/documents/port.py`: a narrow interface Onboarding's decision
service depends on, satisfied by a recording mock until the real module
exists. The mock's `validate_provider_profile` always returns True (there
is no real profile to validate against yet) — Onboarding's own
completeness/submission checks are what actually gate submission today;
this port exists so that call site doesn't need to change when a real
Provider module ships.
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
