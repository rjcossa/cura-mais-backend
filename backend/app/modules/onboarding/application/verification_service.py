"""Verification checks (spec section 14) — external registry adapters
are mocked (`infrastructure/registry_adapters.py`); this service owns
the check lifecycle (PENDING -> COMPLETED/FAILED, retry scheduling).
"""

from __future__ import annotations

import datetime
import uuid

from app.modules.onboarding.domain.events import OnboardingEvent
from app.modules.onboarding.domain.exceptions import OnboardingError
from app.modules.onboarding.domain.models import OnboardingApplication, OnboardingVerificationCheck
from app.modules.onboarding.domain.repositories import OutboxRepository, VerificationCheckRepository
from app.modules.onboarding.infrastructure.registry_adapters import get_registry_adapter

_MAX_RETRIES = 3


class VerificationService:
    def __init__(self, verification_repo: VerificationCheckRepository, outbox_repo: OutboxRepository) -> None:
        self._checks = verification_repo
        self._outbox = outbox_repo

    async def create_check(
        self,
        application: OnboardingApplication,
        *,
        check_type: str,
        provider: str,
        subject_reference: str | None,
        initiated_by: uuid.UUID | None,
    ) -> OnboardingVerificationCheck:
        check = OnboardingVerificationCheck(
            application_id=application.id,
            check_type=check_type,
            provider=provider.upper(),
            subject_reference=subject_reference,
            status="PENDING",
            initiated_by=initiated_by,
        )
        await self._checks.add(check)

        await self._outbox.enqueue(
            OnboardingEvent.VERIFICATION_STARTED,
            {"applicationId": str(application.id), "checkId": str(check.id), "checkType": check_type},
            aggregate_id=application.id,
        )

        # Attempt an automatic result immediately where the provider
        # supports it (mock/real registry adapters); MANUAL always
        # leaves the check PENDING for a reviewer to complete by hand.
        if provider.upper() != "MANUAL" and subject_reference:
            await self._attempt_automatic(check)

        return check

    async def _attempt_automatic(self, check: OnboardingVerificationCheck) -> None:
        adapter = get_registry_adapter(check.provider)
        try:
            result = await adapter.verify(check.check_type, check.subject_reference or "")
        except Exception as exc:  # noqa: BLE001 - registry failures are expected/handled
            check.retry_count += 1
            check.error_message = str(exc)[:500]
            if check.retry_count >= _MAX_RETRIES:
                check.status = "FAILED"
            else:
                check.next_retry_at = datetime.datetime.now(datetime.UTC) + datetime.timedelta(minutes=5)
            return

        check.status = "COMPLETED"
        check.result = result.result
        check.verified_data = result.verified_data
        check.external_reference = result.external_reference
        check.completed_at = datetime.datetime.now(datetime.UTC)

    async def complete_check(
        self,
        application: OnboardingApplication,
        check: OnboardingVerificationCheck,
        *,
        result: str,
        external_reference: str | None,
        verified_data: dict,
        comments: str | None,
    ) -> OnboardingVerificationCheck:
        if check.status == "COMPLETED":
            raise OnboardingError.for_code(
                "ONBOARDING_VERIFICATION_INCOMPLETE", "This verification check has already been completed."
            )

        check.status = "COMPLETED"
        check.result = result
        check.external_reference = external_reference
        check.verified_data = verified_data
        check.completed_at = datetime.datetime.now(datetime.UTC)
        if comments:
            check.error_message = None

        await self._outbox.enqueue(
            OnboardingEvent.VERIFICATION_COMPLETED,
            {"applicationId": str(application.id), "checkId": str(check.id), "result": result},
            aggregate_id=application.id,
        )
        return check

    async def all_required_checks_successful(self, application_id: uuid.UUID) -> bool:
        checks = await self._checks.list_for_application(application_id)
        if not checks:
            return True  # No checks were required/initiated for this application.
        for check in checks:
            if check.status != "COMPLETED":
                return False
            if check.result not in {"MATCH", "PARTIAL_MATCH"}:
                return False
        return True
