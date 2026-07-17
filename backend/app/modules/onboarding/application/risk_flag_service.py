"""Risk flags: raise / resolve (spec section 19)."""

from __future__ import annotations

import datetime
import uuid

from app.modules.onboarding.domain.enums import RESOLVED_RISK_STATUSES
from app.modules.onboarding.domain.events import OnboardingEvent
from app.modules.onboarding.domain.exceptions import OnboardingError
from app.modules.onboarding.domain.models import OnboardingApplication, OnboardingRiskFlag
from app.modules.onboarding.domain.repositories import OutboxRepository, RiskFlagRepository


class RiskFlagService:
    def __init__(self, risk_flag_repo: RiskFlagRepository, outbox_repo: OutboxRepository) -> None:
        self._risk_flags = risk_flag_repo
        self._outbox = outbox_repo

    async def raise_flag(
        self,
        application: OnboardingApplication,
        *,
        flag_code: str,
        risk_level: str,
        description: str,
        raised_by: uuid.UUID | None,
    ) -> OnboardingRiskFlag:
        flag = OnboardingRiskFlag(
            application_id=application.id,
            flag_code=flag_code,
            risk_level=risk_level,
            description=description,
            status="OPEN",
            raised_by=raised_by,
        )
        await self._risk_flags.add(flag)

        await self._outbox.enqueue(
            OnboardingEvent.RISK_FLAG_RAISED,
            {"applicationId": str(application.id), "flagCode": flag_code, "riskLevel": risk_level},
            aggregate_id=application.id,
        )
        return flag

    async def resolve_flag(
        self,
        application: OnboardingApplication,
        flag: OnboardingRiskFlag,
        *,
        status: str,
        resolution_comments: str,
        evidence_reference: str | None,
    ) -> OnboardingRiskFlag:
        if status not in {s.value for s in RESOLVED_RISK_STATUSES} and status != "UNDER_REVIEW":
            raise OnboardingError.for_code(
                "ONBOARDING_APPROVAL_PRECONDITION_FAILED", "Invalid resolution status for a risk flag."
            )

        flag.status = status
        flag.resolution_comments = resolution_comments
        flag.evidence_reference = evidence_reference
        if status in {s.value for s in RESOLVED_RISK_STATUSES}:
            flag.resolved_at = datetime.datetime.now(datetime.UTC)
            await self._outbox.enqueue(
                OnboardingEvent.RISK_FLAG_RESOLVED,
                {"applicationId": str(application.id), "flagCode": flag.flag_code, "status": status},
                aggregate_id=application.id,
            )
        return flag
