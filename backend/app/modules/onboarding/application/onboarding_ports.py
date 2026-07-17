"""Onboarding's public contract for other modules (spec section 21.1,
21.2), mirroring `app.modules.identity.application.identity_ports`. When
the Provider/Institution modules are built for real, their "is this
provider allowed to operate" checks should call `OnboardingQueryService`
rather than reaching into Onboarding's tables directly.
"""

from __future__ import annotations

import datetime
import uuid

from app.modules.onboarding.domain.repositories import ApplicationRepository


class OnboardingQueryService:
    def __init__(self, application_repo: ApplicationRepository) -> None:
        self._applications = application_repo

    async def get_application(self, application_id: uuid.UUID):
        return await self._applications.get_by_id(application_id)

    async def get_current_application(self, applicant_type: str, applicant_entity_id: uuid.UUID):
        return await self._applications.find_open_application(
            applicant_type, applicant_entity_id, "INITIAL_ONBOARDING"
        )

    async def get_application_status(self, application_id: uuid.UUID) -> str | None:
        application = await self._applications.get_by_id(application_id)
        return application.status if application else None

    async def has_approved_application(self, applicant_type: str, applicant_entity_id: uuid.UUID) -> bool:
        # An approved application is no longer "open" (see
        # domain.enums.OPEN_APPLICATION_STATUSES), so this checks the
        # applicant's most recent application directly rather than the
        # open-application lookup.
        recent = await self._applications.find_current_application(applicant_entity_id, applicant_type)
        return recent is not None and recent.status in {"APPROVED", "CONDITIONALLY_APPROVED"}

    async def get_approval_validity(
        self, applicant_type: str, applicant_entity_id: uuid.UUID
    ) -> datetime.datetime | None:
        recent = await self._applications.find_current_application(applicant_entity_id, applicant_type)
        return recent.approval_valid_until if recent else None


class OnboardingCommandService:
    """Thin facade over the individual services for callers (e.g. a
    scheduled job, or a future admin tool) that only need one or two
    operations rather than wiring up every service directly.
    """

    def __init__(
        self,
        application_service,
        document_service,
        assignment_service,
        review_service,
        information_request_service,
        decision_service,
    ) -> None:
        self.applications = application_service
        self.documents = document_service
        self.assignments = assignment_service
        self.reviews = review_service
        self.information_requests = information_request_service
        self.decisions = decision_service
