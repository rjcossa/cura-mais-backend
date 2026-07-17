"""Institution module port (Onboarding spec section 21.5) and a mock
adapter. Same rationale as `app/shared/provider/port.py` — Hospital/
Clinic/Pharmacy institutions don't have a real module yet.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Protocol


@dataclass(slots=True)
class InstitutionProfile:
    institution_id: uuid.UUID
    exists: bool
    active: bool = False


@dataclass(slots=True)
class InstitutionActivationCall:
    institution_id: uuid.UUID
    action: str  # ACTIVATE | SUSPEND
    reference_or_reason: str | None


class InstitutionPort(Protocol):
    async def get_institution_profile(self, institution_id: uuid.UUID) -> InstitutionProfile: ...
    async def validate_institution_profile(self, institution_id: uuid.UUID) -> bool: ...
    async def activate_institution(self, institution_id: uuid.UUID, *, approval_reference: str) -> None: ...
    async def suspend_institution(self, institution_id: uuid.UUID, *, reason: str) -> None: ...


class MockInstitutionAdapter:
    def __init__(self) -> None:
        self.calls: list[InstitutionActivationCall] = []
        self._active: dict[uuid.UUID, bool] = {}

    async def get_institution_profile(self, institution_id: uuid.UUID) -> InstitutionProfile:
        return InstitutionProfile(
            institution_id=institution_id, exists=True, active=self._active.get(institution_id, False)
        )

    async def validate_institution_profile(self, institution_id: uuid.UUID) -> bool:
        return True

    async def activate_institution(self, institution_id: uuid.UUID, *, approval_reference: str) -> None:
        self._active[institution_id] = True
        self.calls.append(InstitutionActivationCall(institution_id, "ACTIVATE", approval_reference))

    async def suspend_institution(self, institution_id: uuid.UUID, *, reason: str) -> None:
        self._active[institution_id] = False
        self.calls.append(InstitutionActivationCall(institution_id, "SUSPEND", reason))


_adapter: MockInstitutionAdapter | None = None


def get_institution_adapter() -> InstitutionPort:
    global _adapter
    if _adapter is None:
        _adapter = MockInstitutionAdapter()
    return _adapter
