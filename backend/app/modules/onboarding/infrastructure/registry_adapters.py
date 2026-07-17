"""External registry verification adapters (spec section 14.3).

No real professional council / company registry / tax authority
integration is specified (the spec's own example uses `"provider":
"MANUAL"` — a human reviewer entering the result themselves). This
module provides that manual path for real use today, plus a mock
"automatic" adapter so the full verification-check lifecycle (PENDING ->
COMPLETED, retry-on-failure, etc.) can be exercised end-to-end without a
real registry to call. Swapping in a real registry means implementing
`RegistryAdapter` differently — `VerificationService` doesn't change.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass
from typing import Protocol


@dataclass(slots=True)
class RegistryCheckResult:
    result: str  # VerificationCheckResult value
    verified_data: dict
    external_reference: str | None = None
    error_code: str | None = None
    error_message: str | None = None


class RegistryAdapter(Protocol):
    async def verify(self, check_type: str, subject_reference: str) -> RegistryCheckResult: ...


class ManualRegistryAdapter:
    """The `MANUAL` provider (spec 14.1's example) — a reviewer completes
    the check themselves via `POST .../verification-checks/{id}/complete`.
    This adapter never auto-completes; `verify()` always signals
    "no automatic result available."
    """

    async def verify(self, check_type: str, subject_reference: str) -> RegistryCheckResult:
        return RegistryCheckResult(
            result="MANUAL_REVIEW_REQUIRED",
            verified_data={},
            error_message="Manual provider: a reviewer must complete this check directly.",
        )


class MockAutomaticRegistryAdapter:
    """Stands in for a real registry integration. Deterministic and
    offline: treats any subject reference ending in specific suffixes as
    a signal for tests/demos (`-NOMATCH` -> NO_MATCH, `-FAIL` -> raises),
    otherwise returns MATCH with a plausible payload.
    """

    async def verify(self, check_type: str, subject_reference: str) -> RegistryCheckResult:
        if subject_reference.endswith("-FAIL"):
            raise ConnectionError("Mock registry unavailable")
        if subject_reference.endswith("-NOMATCH"):
            return RegistryCheckResult(
                result="NO_MATCH",
                verified_data={"subjectReference": subject_reference},
                external_reference=f"MOCK-{check_type}-NOMATCH",
            )
        return RegistryCheckResult(
            result="MATCH",
            verified_data={
                "subjectReference": subject_reference,
                "status": "ACTIVE",
                "verifiedAt": datetime.datetime.now(datetime.UTC).isoformat(),
            },
            external_reference=f"MOCK-{check_type}-{subject_reference}",
        )


_adapters: dict[str, RegistryAdapter] = {}


def get_registry_adapter(provider: str) -> RegistryAdapter:
    provider = provider.upper()
    if provider not in _adapters:
        _adapters[provider] = ManualRegistryAdapter() if provider == "MANUAL" else MockAutomaticRegistryAdapter()
    return _adapters[provider]
