"""SQLAlchemy implementations of the repository ports declared in
`domain/repositories.py`.
"""

from __future__ import annotations

import datetime
import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.onboarding.domain.enums import OPEN_APPLICATION_STATUSES, RiskLevel
from app.modules.onboarding.domain.models import (
    EventOutbox,
    OnboardingApplication,
    OnboardingApplicationAssignment,
    OnboardingApplicationDocument,
    OnboardingApplicationNote,
    OnboardingApplicationParty,
    OnboardingApplicationSection,
    OnboardingApplicationStatusHistory,
    OnboardingDecision,
    OnboardingDocumentRequirement,
    OnboardingDocumentReview,
    OnboardingInformationRequest,
    OnboardingInformationRequestItem,
    OnboardingReverificationCase,
    OnboardingReview,
    OnboardingReviewChecklist,
    OnboardingReviewChecklistItem,
    OnboardingRiskFlag,
    OnboardingVerificationCheck,
)


class SqlAlchemyApplicationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, application: OnboardingApplication) -> None:
        self._session.add(application)
        await self._session.flush()

    async def get_by_id(self, application_id: uuid.UUID) -> OnboardingApplication | None:
        stmt = select(OnboardingApplication).where(OnboardingApplication.id == application_id)
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def get_by_id_for_update(self, application_id: uuid.UUID) -> OnboardingApplication | None:
        stmt = select(OnboardingApplication).where(OnboardingApplication.id == application_id).with_for_update()
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def get_by_application_number(self, application_number: str) -> OnboardingApplication | None:
        stmt = select(OnboardingApplication).where(
            OnboardingApplication.application_number == application_number
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def find_open_application(
        self, applicant_type: str, applicant_entity_id: uuid.UUID, purpose: str
    ) -> OnboardingApplication | None:
        stmt = select(OnboardingApplication).where(
            OnboardingApplication.applicant_type == applicant_type,
            OnboardingApplication.applicant_entity_id == applicant_entity_id,
            OnboardingApplication.application_purpose == purpose,
            OnboardingApplication.status.in_([s.value for s in OPEN_APPLICATION_STATUSES]),
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def find_current_application(
        self, applicant_user_id: uuid.UUID, applicant_type: str | None
    ) -> OnboardingApplication | None:
        conditions = [OnboardingApplication.applicant_user_id == applicant_user_id]
        if applicant_type:
            conditions.append(OnboardingApplication.applicant_type == applicant_type)
        stmt = (
            select(OnboardingApplication)
            .where(*conditions)
            .order_by(OnboardingApplication.created_at.desc())
            .limit(1)
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def search(
        self,
        *,
        applicant_type: str | None = None,
        status: str | None = None,
        application_number: str | None = None,
        assigned_reviewer_id: uuid.UUID | None = None,
        unassigned: bool | None = None,
        submitted_from: datetime.date | None = None,
        submitted_to: datetime.date | None = None,
        page: int = 0,
        size: int = 20,
    ) -> tuple[list[OnboardingApplication], int]:
        conditions = []
        if applicant_type:
            conditions.append(OnboardingApplication.applicant_type == applicant_type)
        if status:
            conditions.append(OnboardingApplication.status == status)
        if application_number:
            conditions.append(OnboardingApplication.application_number == application_number)
        if assigned_reviewer_id:
            conditions.append(OnboardingApplication.current_reviewer_id == assigned_reviewer_id)
        if unassigned:
            conditions.append(OnboardingApplication.current_reviewer_id.is_(None))
        if submitted_from:
            conditions.append(OnboardingApplication.submitted_at >= submitted_from)
        if submitted_to:
            conditions.append(OnboardingApplication.submitted_at <= submitted_to)

        count_stmt = select(func.count()).select_from(OnboardingApplication).where(*conditions)
        total = (await self._session.execute(count_stmt)).scalar_one()

        stmt = (
            select(OnboardingApplication)
            .where(*conditions)
            .order_by(OnboardingApplication.submitted_at.desc().nulls_last(), OnboardingApplication.created_at.desc())
            .offset(page * size)
            .limit(size)
        )
        rows = list((await self._session.execute(stmt)).scalars().all())
        return rows, total

    async def next_sequence_number(self, applicant_type: str, year: int) -> int:
        """Counts existing applications of this type/year to derive the
        next sequence number. Not perfectly race-free under concurrent
        creates without a dedicated DB sequence per (type, year) — the
        `application_number` column's UNIQUE constraint is the backstop,
        and `ApplicationService.create_application` retries once on a
        collision. Acceptable for onboarding's volume (nowhere near
        create-heavy enough to need a real distributed sequence).
        """
        prefix = f"ONB-{_TYPE_CODES.get(applicant_type, applicant_type[:3].upper())}-{year}-"
        stmt = select(func.count()).select_from(OnboardingApplication).where(
            OnboardingApplication.application_number.like(f"{prefix}%")
        )
        count = (await self._session.execute(stmt)).scalar_one()
        return count + 1

    async def add_party(self, party: OnboardingApplicationParty) -> None:
        self._session.add(party)
        await self._session.flush()

    async def list_parties(self, application_id: uuid.UUID) -> list[OnboardingApplicationParty]:
        stmt = select(OnboardingApplicationParty).where(
            OnboardingApplicationParty.application_id == application_id
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def add_section(self, section: OnboardingApplicationSection) -> None:
        self._session.add(section)
        await self._session.flush()

    async def get_section(
        self, application_id: uuid.UUID, section_code: str
    ) -> OnboardingApplicationSection | None:
        stmt = select(OnboardingApplicationSection).where(
            OnboardingApplicationSection.application_id == application_id,
            OnboardingApplicationSection.section_code == section_code,
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def list_sections(self, application_id: uuid.UUID) -> list[OnboardingApplicationSection]:
        stmt = select(OnboardingApplicationSection).where(
            OnboardingApplicationSection.application_id == application_id
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def add_status_history(self, entry: OnboardingApplicationStatusHistory) -> None:
        self._session.add(entry)
        await self._session.flush()

    async def list_status_history(
        self, application_id: uuid.UUID
    ) -> list[OnboardingApplicationStatusHistory]:
        stmt = (
            select(OnboardingApplicationStatusHistory)
            .where(OnboardingApplicationStatusHistory.application_id == application_id)
            .order_by(OnboardingApplicationStatusHistory.created_at)
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def add_note(self, note: OnboardingApplicationNote) -> None:
        self._session.add(note)
        await self._session.flush()

    async def list_notes(self, application_id: uuid.UUID) -> list[OnboardingApplicationNote]:
        stmt = (
            select(OnboardingApplicationNote)
            .where(OnboardingApplicationNote.application_id == application_id)
            .order_by(OnboardingApplicationNote.created_at)
        )
        return list((await self._session.execute(stmt)).scalars().all())


_TYPE_CODES = {"DOCTOR": "DOC", "NUTRITIONIST": "NUT", "HOSPITAL": "HOS", "CLINIC": "CLI", "PHARMACY": "PHA"}


class SqlAlchemyDocumentRequirementRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_applicable(
        self, applicant_type: str, application_purpose: str, country_code: str | None
    ) -> list[OnboardingDocumentRequirement]:
        now = datetime.datetime.now(datetime.UTC)
        conditions = [
            OnboardingDocumentRequirement.applicant_type == applicant_type,
            OnboardingDocumentRequirement.active.is_(True),
            OnboardingDocumentRequirement.effective_from <= now,
            (OnboardingDocumentRequirement.effective_until.is_(None))
            | (OnboardingDocumentRequirement.effective_until > now),
            (OnboardingDocumentRequirement.application_purpose.is_(None))
            | (OnboardingDocumentRequirement.application_purpose == application_purpose),
        ]
        if country_code:
            conditions.append(
                (OnboardingDocumentRequirement.country_code.is_(None))
                | (OnboardingDocumentRequirement.country_code == country_code)
            )
        stmt = select(OnboardingDocumentRequirement).where(*conditions)
        return list((await self._session.execute(stmt)).scalars().all())

    async def get_by_id(self, requirement_id: uuid.UUID) -> OnboardingDocumentRequirement | None:
        stmt = select(OnboardingDocumentRequirement).where(OnboardingDocumentRequirement.id == requirement_id)
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def add(self, requirement: OnboardingDocumentRequirement) -> None:
        self._session.add(requirement)
        await self._session.flush()


class SqlAlchemyApplicationDocumentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, document: OnboardingApplicationDocument) -> None:
        self._session.add(document)
        await self._session.flush()

    async def get_by_id(self, application_document_id: uuid.UUID) -> OnboardingApplicationDocument | None:
        stmt = select(OnboardingApplicationDocument).where(
            OnboardingApplicationDocument.id == application_document_id
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def list_current(self, application_id: uuid.UUID) -> list[OnboardingApplicationDocument]:
        stmt = select(OnboardingApplicationDocument).where(
            OnboardingApplicationDocument.application_id == application_id,
            OnboardingApplicationDocument.current_version.is_(True),
            OnboardingApplicationDocument.deleted_at.is_(None),
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def add_review(self, review: OnboardingDocumentReview) -> None:
        self._session.add(review)
        await self._session.flush()

    async def list_reviews(self, application_document_id: uuid.UUID) -> list[OnboardingDocumentReview]:
        stmt = (
            select(OnboardingDocumentReview)
            .where(OnboardingDocumentReview.application_document_id == application_document_id)
            .order_by(OnboardingDocumentReview.created_at)
        )
        return list((await self._session.execute(stmt)).scalars().all())


class SqlAlchemyAssignmentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, assignment: OnboardingApplicationAssignment) -> None:
        self._session.add(assignment)
        await self._session.flush()

    async def get_active_primary(
        self, application_id: uuid.UUID
    ) -> OnboardingApplicationAssignment | None:
        stmt = select(OnboardingApplicationAssignment).where(
            OnboardingApplicationAssignment.application_id == application_id,
            OnboardingApplicationAssignment.active.is_(True),
            OnboardingApplicationAssignment.assignment_type == "PRIMARY_REVIEW",
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def list_active(self, application_id: uuid.UUID) -> list[OnboardingApplicationAssignment]:
        stmt = select(OnboardingApplicationAssignment).where(
            OnboardingApplicationAssignment.application_id == application_id,
            OnboardingApplicationAssignment.active.is_(True),
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def list_by_reviewer(
        self, reviewer_id: uuid.UUID, active_only: bool
    ) -> list[OnboardingApplicationAssignment]:
        conditions = [OnboardingApplicationAssignment.reviewer_id == reviewer_id]
        if active_only:
            conditions.append(OnboardingApplicationAssignment.active.is_(True))
        stmt = select(OnboardingApplicationAssignment).where(*conditions)
        return list((await self._session.execute(stmt)).scalars().all())


class SqlAlchemyReviewRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, review: OnboardingReview) -> None:
        self._session.add(review)
        await self._session.flush()

    async def get_by_id(self, review_id: uuid.UUID) -> OnboardingReview | None:
        stmt = select(OnboardingReview).where(OnboardingReview.id == review_id)
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def get_active_for_application(self, application_id: uuid.UUID) -> OnboardingReview | None:
        stmt = (
            select(OnboardingReview)
            .where(
                OnboardingReview.application_id == application_id,
                OnboardingReview.status == "IN_PROGRESS",
            )
            .order_by(OnboardingReview.started_at.desc())
            .limit(1)
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def list_for_application(self, application_id: uuid.UUID) -> list[OnboardingReview]:
        stmt = (
            select(OnboardingReview)
            .where(OnboardingReview.application_id == application_id)
            .order_by(OnboardingReview.started_at)
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def find_checklist_template(
        self, applicant_type: str, review_type: str, application_purpose: str | None
    ) -> OnboardingReviewChecklist | None:
        conditions = [
            OnboardingReviewChecklist.applicant_type == applicant_type,
            OnboardingReviewChecklist.review_type == review_type,
            OnboardingReviewChecklist.active.is_(True),
        ]
        stmt = select(OnboardingReviewChecklist).where(*conditions).order_by(
            OnboardingReviewChecklist.application_purpose.is_(None)
        )
        results = list((await self._session.execute(stmt)).scalars().all())
        if not results:
            return None
        # Prefer a purpose-specific template over a generic (NULL-purpose) one.
        for template in results:
            if template.application_purpose == application_purpose:
                return template
        for template in results:
            if template.application_purpose is None:
                return template
        return results[0]

    async def add_checklist_template(self, template: OnboardingReviewChecklist) -> None:
        self._session.add(template)
        await self._session.flush()

    async def add_checklist_item(self, item: OnboardingReviewChecklistItem) -> None:
        self._session.add(item)
        await self._session.flush()

    async def list_checklist_items(self, review_id: uuid.UUID) -> list[OnboardingReviewChecklistItem]:
        stmt = select(OnboardingReviewChecklistItem).where(OnboardingReviewChecklistItem.review_id == review_id)
        return list((await self._session.execute(stmt)).scalars().all())

    async def get_checklist_item(self, item_id: uuid.UUID) -> OnboardingReviewChecklistItem | None:
        stmt = select(OnboardingReviewChecklistItem).where(OnboardingReviewChecklistItem.id == item_id)
        return (await self._session.execute(stmt)).scalar_one_or_none()


class SqlAlchemyVerificationCheckRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, check: OnboardingVerificationCheck) -> None:
        self._session.add(check)
        await self._session.flush()

    async def get_by_id(self, check_id: uuid.UUID) -> OnboardingVerificationCheck | None:
        stmt = select(OnboardingVerificationCheck).where(OnboardingVerificationCheck.id == check_id)
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def list_for_application(self, application_id: uuid.UUID) -> list[OnboardingVerificationCheck]:
        stmt = select(OnboardingVerificationCheck).where(
            OnboardingVerificationCheck.application_id == application_id
        )
        return list((await self._session.execute(stmt)).scalars().all())


class SqlAlchemyInformationRequestRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, request: OnboardingInformationRequest) -> None:
        self._session.add(request)
        await self._session.flush()

    async def get_by_id(self, request_id: uuid.UUID) -> OnboardingInformationRequest | None:
        stmt = select(OnboardingInformationRequest).where(OnboardingInformationRequest.id == request_id)
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def list_for_application(self, application_id: uuid.UUID) -> list[OnboardingInformationRequest]:
        stmt = (
            select(OnboardingInformationRequest)
            .where(OnboardingInformationRequest.application_id == application_id)
            .order_by(OnboardingInformationRequest.created_at)
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def list_open_overdue(self, as_of: datetime.date) -> list[OnboardingInformationRequest]:
        stmt = select(OnboardingInformationRequest).where(
            OnboardingInformationRequest.status.in_(["OPEN", "PARTIALLY_RESPONDED"]),
            OnboardingInformationRequest.response_due_date.is_not(None),
            OnboardingInformationRequest.response_due_date < as_of,
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def add_item(self, item: OnboardingInformationRequestItem) -> None:
        self._session.add(item)
        await self._session.flush()

    async def list_items(self, request_id: uuid.UUID) -> list[OnboardingInformationRequestItem]:
        stmt = select(OnboardingInformationRequestItem).where(
            OnboardingInformationRequestItem.information_request_id == request_id
        )
        return list((await self._session.execute(stmt)).scalars().all())


class SqlAlchemyDecisionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, decision: OnboardingDecision) -> None:
        self._session.add(decision)
        await self._session.flush()

    async def list_for_application(self, application_id: uuid.UUID) -> list[OnboardingDecision]:
        stmt = (
            select(OnboardingDecision)
            .where(OnboardingDecision.application_id == application_id)
            .order_by(OnboardingDecision.created_at)
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def get_latest(self, application_id: uuid.UUID) -> OnboardingDecision | None:
        stmt = (
            select(OnboardingDecision)
            .where(OnboardingDecision.application_id == application_id)
            .order_by(OnboardingDecision.created_at.desc())
            .limit(1)
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()


class SqlAlchemyRiskFlagRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, flag: OnboardingRiskFlag) -> None:
        self._session.add(flag)
        await self._session.flush()

    async def get_by_id(self, flag_id: uuid.UUID) -> OnboardingRiskFlag | None:
        stmt = select(OnboardingRiskFlag).where(OnboardingRiskFlag.id == flag_id)
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def list_for_application(self, application_id: uuid.UUID) -> list[OnboardingRiskFlag]:
        stmt = select(OnboardingRiskFlag).where(OnboardingRiskFlag.application_id == application_id)
        return list((await self._session.execute(stmt)).scalars().all())

    async def has_unresolved_blocking(self, application_id: uuid.UUID) -> bool:
        blocking_levels = [level.value for level in (RiskLevel.HIGH, RiskLevel.CRITICAL)]
        stmt = select(func.count()).select_from(OnboardingRiskFlag).where(
            OnboardingRiskFlag.application_id == application_id,
            OnboardingRiskFlag.risk_level.in_(blocking_levels),
            OnboardingRiskFlag.status.in_(["OPEN", "UNDER_REVIEW"]),
        )
        count = (await self._session.execute(stmt)).scalar_one()
        return count > 0


class SqlAlchemyReverificationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, case: OnboardingReverificationCase) -> None:
        self._session.add(case)
        await self._session.flush()

    async def get_by_id(self, case_id: uuid.UUID) -> OnboardingReverificationCase | None:
        stmt = select(OnboardingReverificationCase).where(OnboardingReverificationCase.id == case_id)
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def list_open_for_application(
        self, application_id: uuid.UUID
    ) -> list[OnboardingReverificationCase]:
        stmt = select(OnboardingReverificationCase).where(
            OnboardingReverificationCase.original_application_id == application_id,
            OnboardingReverificationCase.status == "OPEN",
        )
        return list((await self._session.execute(stmt)).scalars().all())


class SqlAlchemyOutboxRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def enqueue(
        self,
        event_type: str,
        payload: dict,
        *,
        aggregate_id: uuid.UUID | None = None,
        aggregate_type: str = "OnboardingApplication",
    ) -> None:
        self._session.add(
            EventOutbox(
                event_type=event_type,
                aggregate_type=aggregate_type,
                aggregate_id=aggregate_id,
                payload=payload,
            )
        )
        await self._session.flush()
