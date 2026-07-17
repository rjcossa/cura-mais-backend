"""Application creation, section updates, submission, and withdrawal
(spec sections 7, 8.1-8.6, transaction boundaries in 27.1-27.2).
"""

from __future__ import annotations

import datetime
import uuid

from app.modules.onboarding.application import status_helper
from app.modules.onboarding.application.completeness_service import CompletenessService
from app.modules.onboarding.application.requirements_service import RequirementsService
from app.modules.onboarding.application.section_definitions import (
    DOCUMENTS_SECTION_CODE,
    compute_section_status,
    get_section_definition,
    get_section_definitions,
)
from app.modules.onboarding.domain.enums import ApplicationStatus, PartyType
from app.modules.onboarding.domain.events import OnboardingEvent, OnboardingNotification
from app.modules.onboarding.domain.exceptions import OnboardingError
from app.modules.onboarding.domain.models import (
    OnboardingApplication,
    OnboardingApplicationParty,
    OnboardingApplicationSection,
    OnboardingApplicationStatusHistory,
)
from app.modules.onboarding.domain.repositories import ApplicationRepository, OutboxRepository
from app.modules.onboarding.domain.workflow import is_transition_allowed
from app.modules.onboarding.infrastructure.identity_adapter import IdentityPort

# Individual-professional applicant types use the user's own id as their
# "entity" id (see module docstring discussion in this file's class);
# institutional types get a freshly generated one per new application.
_INDIVIDUAL_APPLICANT_TYPES = {"DOCTOR", "NUTRITIONIST"}


class ApplicationService:
    def __init__(
        self,
        application_repo: ApplicationRepository,
        requirements_service: RequirementsService,
        completeness_service: CompletenessService,
        outbox_repo: OutboxRepository,
        identity: IdentityPort,
    ) -> None:
        self._applications = application_repo
        self._requirements = requirements_service
        self._completeness = completeness_service
        self._outbox = outbox_repo
        self._identity = identity

    # --- Creation (spec 7.1) ---------------------------------------------

    async def create_application(
        self,
        *,
        applicant_type: str,
        applicant_user_id: uuid.UUID,
        purpose: str = "INITIAL_ONBOARDING",
        applicant_entity_id: uuid.UUID | None = None,
        applicant_full_name: str | None = None,
    ) -> OnboardingApplication:
        if not await self._identity.is_user_active(applicant_user_id):
            raise OnboardingError.for_code(
                "ONBOARDING_APPROVAL_PRECONDITION_FAILED", "The applicant's account is not active."
            )

        entity_id = applicant_entity_id or (
            applicant_user_id if applicant_type in _INDIVIDUAL_APPLICANT_TYPES else uuid.uuid4()
        )

        existing = await self._applications.find_open_application(applicant_type, entity_id, purpose)
        if existing is not None:
            raise OnboardingError.for_code("ONBOARDING_APPLICATION_ALREADY_EXISTS")

        application_number = await self._generate_application_number(applicant_type)

        application = OnboardingApplication(
            application_number=application_number,
            applicant_type=applicant_type,
            applicant_user_id=applicant_user_id,
            applicant_entity_id=entity_id,
            application_purpose=purpose,
            status=ApplicationStatus.DRAFT.value,
            created_by=applicant_user_id,
        )
        await self._applications.add(application)

        await self._applications.add_status_history(
            _history_entry(application, previous=None, new=ApplicationStatus.DRAFT, changed_by=applicant_user_id)
        )

        await self._applications.add_party(
            OnboardingApplicationParty(
                application_id=application.id,
                party_type=PartyType.PRIMARY_APPLICANT.value,
                related_user_id=applicant_user_id,
                full_name=applicant_full_name,
            )
        )

        for section_def in get_section_definitions(applicant_type):
            await self._applications.add_section(
                OnboardingApplicationSection(
                    application_id=application.id,
                    section_code=section_def.code,
                    status="NOT_STARTED",
                )
            )

        await self._outbox.enqueue(
            OnboardingEvent.APPLICATION_CREATED,
            {
                "applicationId": str(application.id),
                "applicationNumber": application_number,
                "applicantType": applicant_type,
                "applicantUserId": str(applicant_user_id),
                "notificationCommand": OnboardingNotification.APPLICATION_CREATED,
                "channel": "EMAIL",
            },
            aggregate_id=application.id,
        )
        return application

    async def _generate_application_number(self, applicant_type: str) -> str:
        year = datetime.datetime.now(datetime.UTC).year
        sequence = await self._applications.next_sequence_number(applicant_type, year)
        type_code = _TYPE_CODES.get(applicant_type, applicant_type[:3].upper())
        return f"ONB-{type_code}-{year}-{sequence:06d}"

    # --- Reads (spec 8.1-8.3) ---------------------------------------------

    async def get_current_application(
        self, applicant_user_id: uuid.UUID, applicant_type: str | None
    ) -> OnboardingApplication | None:
        return await self._applications.find_current_application(applicant_user_id, applicant_type)

    async def require_owned_application(
        self, application_id: uuid.UUID, applicant_user_id: uuid.UUID
    ) -> OnboardingApplication:
        application = await self._applications.get_by_id(application_id)
        if application is None or application.applicant_user_id != applicant_user_id:
            raise OnboardingError.for_code("ONBOARDING_APPLICATION_NOT_FOUND")
        return application

    # --- Section updates (spec 8.4) ---------------------------------------

    async def update_section(
        self, application: OnboardingApplication, section_code: str, data: dict
    ) -> OnboardingApplicationSection:
        if application.status not in {s.value for s in _EDITABLE}:
            raise OnboardingError.for_code("ONBOARDING_APPLICATION_NOT_EDITABLE")

        if section_code == DOCUMENTS_SECTION_CODE:
            raise OnboardingError.for_code(
                "ONBOARDING_APPLICATION_STATE_INVALID",
                "The documents section is derived from uploaded documents and cannot be edited directly.",
            )

        definition = get_section_definition(application.applicant_type, section_code)
        if definition is None:
            raise OnboardingError.for_code(
                "ONBOARDING_APPLICATION_STATE_INVALID",
                f"'{section_code}' is not a valid section for {application.applicant_type} applications.",
            )

        section = await self._applications.get_section(application.id, section_code)
        status, errors = compute_section_status(definition, data)

        if section is None:
            section = OnboardingApplicationSection(
                application_id=application.id,
                section_code=section_code,
            )
            await self._applications.add_section(section)

        section.data = data
        section.status = status
        section.validation_errors = errors or None
        section.completion_percentage = 100 if status == "COMPLETE" else (50 if data else 0)
        if status == "COMPLETE":
            section.completed_at = datetime.datetime.now(datetime.UTC)

        # Keep the application's summary completion_percentage fresh.
        result = await self._completeness.calculate(application)
        application.completion_percentage = result.completion_percentage

        return section

    # --- Submission (spec 8.5, 27.2) ---------------------------------------

    async def submit_application(
        self, application: OnboardingApplication, *, submission_version: int, submitted_by: uuid.UUID
    ) -> None:
        if application.status not in _SUBMITTABLE_STATUSES:
            if application.status in _ALREADY_SUBMITTED_STATUSES:
                raise OnboardingError.for_code("ONBOARDING_APPLICATION_ALREADY_SUBMITTED")
            raise OnboardingError.for_code("ONBOARDING_APPLICATION_STATE_INVALID")

        if submission_version != application.submission_version:
            raise OnboardingError.for_code("ONBOARDING_APPLICATION_VERSION_CONFLICT")

        if not await self._identity.is_user_active(submitted_by):
            raise OnboardingError.for_code(
                "ONBOARDING_APPROVAL_PRECONDITION_FAILED", "The applicant's account is not active."
            )

        completeness = await self._completeness.calculate(application)
        if not completeness.complete:
            raise OnboardingError.for_code(
                "ONBOARDING_APPLICATION_INCOMPLETE",
                details={
                    "missingFields": completeness.missing_fields,
                    "missingDocuments": completeness.missing_documents,
                    "invalidDocuments": completeness.invalid_documents,
                    "expiredDocuments": completeness.expired_documents,
                    "processingDocuments": completeness.processing_documents,
                },
            )

        now = datetime.datetime.now(datetime.UTC)
        application.submission_version += 1
        application.submitted_at = now

        was_resubmission = application.status == ApplicationStatus.RESUBMITTED.value

        await status_helper.transition(
            application, ApplicationStatus.SUBMITTED, self._applications, changed_by=submitted_by
        )
        await self._outbox.enqueue(
            OnboardingEvent.APPLICATION_RESUBMITTED if was_resubmission else OnboardingEvent.APPLICATION_SUBMITTED,
            {"applicationId": str(application.id), "applicationNumber": application.application_number},
            aggregate_id=application.id,
        )

        # No explicit "move to queue" endpoint exists in the spec; a
        # freshly submitted application is immediately queued for review
        # (spec 6.1's diagram allows SUBMITTED -> QUEUED directly).
        application.queued_at = now
        await status_helper.transition(
            application, ApplicationStatus.QUEUED, self._applications, changed_by=submitted_by
        )
        await self._outbox.enqueue(
            OnboardingEvent.APPLICATION_QUEUED,
            {"applicationId": str(application.id)},
            aggregate_id=application.id,
        )

    # --- Withdrawal (spec 8.6) ----------------------------------------------

    async def withdraw_application(
        self, application: OnboardingApplication, *, reason: str, withdrawn_by: uuid.UUID
    ) -> None:
        current = ApplicationStatus(application.status)
        if not is_transition_allowed(current, ApplicationStatus.WITHDRAWN):
            raise OnboardingError.for_code("ONBOARDING_APPLICATION_WITHDRAWAL_NOT_ALLOWED")

        await status_helper.transition(
            application,
            ApplicationStatus.WITHDRAWN,
            self._applications,
            changed_by=withdrawn_by,
            comments=reason,
        )
        await self._outbox.enqueue(
            OnboardingEvent.APPLICATION_WITHDRAWN,
            {"applicationId": str(application.id), "reason": reason},
            aggregate_id=application.id,
        )


_TYPE_CODES = {"DOCTOR": "DOC", "NUTRITIONIST": "NUT", "HOSPITAL": "HOS", "CLINIC": "CLI", "PHARMACY": "PHA"}
_EDITABLE = {ApplicationStatus.DRAFT, ApplicationStatus.ADDITIONAL_INFORMATION_REQUIRED, ApplicationStatus.RESUBMITTED}
_SUBMITTABLE_STATUSES = {
    ApplicationStatus.DRAFT.value,
    ApplicationStatus.ADDITIONAL_INFORMATION_REQUIRED.value,
    ApplicationStatus.RESUBMITTED.value,
}
_ALREADY_SUBMITTED_STATUSES = {
    ApplicationStatus.SUBMITTED.value,
    ApplicationStatus.QUEUED.value,
    ApplicationStatus.UNDER_REVIEW.value,
    ApplicationStatus.PENDING_SECOND_LEVEL_REVIEW.value,
    ApplicationStatus.PENDING_APPROVAL.value,
    ApplicationStatus.APPROVED.value,
    ApplicationStatus.CONDITIONALLY_APPROVED.value,
}


def _history_entry(application, *, previous, new, changed_by):
    return OnboardingApplicationStatusHistory(
        application_id=application.id,
        previous_status=previous.value if previous else None,
        new_status=new.value,
        changed_by=changed_by,
    )
