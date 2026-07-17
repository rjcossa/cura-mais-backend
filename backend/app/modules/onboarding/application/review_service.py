"""Review lifecycle: start / checklist / document review / complete
(spec section 13).
"""

from __future__ import annotations

import datetime
import uuid

from app.modules.onboarding.application import status_helper
from app.modules.onboarding.domain.enums import ApplicationStatus
from app.modules.onboarding.domain.events import OnboardingEvent
from app.modules.onboarding.domain.exceptions import OnboardingError
from app.modules.onboarding.domain.models import (
    OnboardingApplication,
    OnboardingDocumentReview,
    OnboardingReview,
    OnboardingReviewChecklistItem,
)
from app.modules.onboarding.domain.repositories import (
    ApplicationDocumentRepository,
    ApplicationRepository,
    AssignmentRepository,
    OutboxRepository,
    ReviewRepository,
    RiskFlagRepository,
)

# Default checklist used when no configured template matches (spec 13.2's
# example doctor checklist) — a sensible generic fallback so review can
# always start even before an admin configures applicant-type-specific
# templates via ONBOARDING_CHECKLIST_MANAGE.
_DEFAULT_CHECKLIST_ITEMS = [
    {"code": "IDENTITY_DOCUMENT_VALID", "description": "Identity document is valid.", "mandatory": True},
    {"code": "MANDATORY_DOCUMENTS_PRESENT", "description": "Mandatory documents are present.", "mandatory": True},
    {"code": "NO_EXPIRED_DOCUMENT", "description": "No expired mandatory document.", "mandatory": True},
    {"code": "DECLARATIONS_ACCEPTED", "description": "Declarations accepted.", "mandatory": True},
    {"code": "NO_UNRESOLVED_RISK_FLAGS", "description": "No unresolved risk flags.", "mandatory": True},
]


class ReviewService:
    def __init__(
        self,
        application_repo: ApplicationRepository,
        review_repo: ReviewRepository,
        document_repo: ApplicationDocumentRepository,
        assignment_repo: AssignmentRepository,
        risk_flag_repo: RiskFlagRepository,
        outbox_repo: OutboxRepository,
    ) -> None:
        self._applications = application_repo
        self._reviews = review_repo
        self._documents = document_repo
        self._assignments = assignment_repo
        self._risk_flags = risk_flag_repo
        self._outbox = outbox_repo

    async def start_review(
        self, application: OnboardingApplication, *, review_type: str, reviewer_id: uuid.UUID
    ) -> OnboardingReview:
        assignment = await self._assignments.get_active_primary(application.id)
        if assignment is None or assignment.reviewer_id != reviewer_id:
            raise OnboardingError.for_code("ONBOARDING_APPLICATION_NOT_ASSIGNED")

        existing = await self._reviews.get_active_for_application(application.id)
        if existing is not None:
            raise OnboardingError.for_code("ONBOARDING_REVIEW_ALREADY_STARTED")

        review = OnboardingReview(
            application_id=application.id, reviewer_id=reviewer_id, review_type=review_type, status="IN_PROGRESS"
        )
        await self._reviews.add(review)

        template = await self._reviews.find_checklist_template(
            application.applicant_type, review_type, application.application_purpose
        )
        items = template.items if template else _DEFAULT_CHECKLIST_ITEMS
        for item in items:
            await self._reviews.add_checklist_item(
                OnboardingReviewChecklistItem(
                    review_id=review.id,
                    item_code=item["code"],
                    item_description=item["description"],
                    mandatory=item.get("mandatory", True),
                )
            )

        if application.status in {
            ApplicationStatus.QUEUED.value,
            ApplicationStatus.SUBMITTED.value,
            ApplicationStatus.RESUBMITTED.value,
        }:
            application.review_started_at = datetime.datetime.now(datetime.UTC)
            await status_helper.transition(
                application, ApplicationStatus.UNDER_REVIEW, self._applications, changed_by=reviewer_id
            )

        await self._outbox.enqueue(
            OnboardingEvent.REVIEW_STARTED,
            {"applicationId": str(application.id), "reviewId": str(review.id), "reviewType": review_type},
            aggregate_id=application.id,
        )
        return review

    async def update_checklist_item(
        self,
        review: OnboardingReview,
        item: OnboardingReviewChecklistItem,
        *,
        result: str,
        comments: str | None,
        evidence_reference: str | None,
        completed_by: uuid.UUID,
    ) -> OnboardingReviewChecklistItem:
        if review.status != "IN_PROGRESS":
            raise OnboardingError.for_code("ONBOARDING_REVIEW_ALREADY_STARTED", "This review is no longer active.")

        item.result = result
        item.comments = comments
        item.evidence_reference = evidence_reference
        item.completed_by = completed_by
        item.completed_at = datetime.datetime.now(datetime.UTC)
        return item

    async def review_document(
        self,
        application: OnboardingApplication,
        application_document,
        *,
        decision: str,
        comments: str | None,
        verification_method: str | None,
        verified_document_number: str | None,
        verified_expiry_date,
        reviewer_id: uuid.UUID,
    ) -> OnboardingDocumentReview:
        if not application_document.current_version:
            raise OnboardingError.for_code(
                "ONBOARDING_DOCUMENT_NOT_AVAILABLE", "Only the current document version may be reviewed."
            )
        if decision == "REJECTED" and not comments:
            raise OnboardingError.for_code("ONBOARDING_DOCUMENT_METADATA_INVALID", "Comments are required to reject a document.")

        review = OnboardingDocumentReview(
            application_document_id=application_document.id,
            reviewer_id=reviewer_id,
            decision=decision,
            verification_method=verification_method,
            comments=comments,
            verified_document_number=verified_document_number,
            verified_expiry_date=verified_expiry_date,
        )
        await self._documents.add_review(review)

        application_document.review_status = decision
        await self._outbox.enqueue(
            OnboardingEvent.DOCUMENT_REVIEWED,
            {
                "applicationId": str(application.id),
                "applicationDocumentId": str(application_document.id),
                "decision": decision,
            },
            aggregate_id=application.id,
        )
        return review

    async def complete_review(
        self,
        application: OnboardingApplication,
        review: OnboardingReview,
        *,
        recommendation: str,
        comments: str | None,
        completed_by: uuid.UUID,
    ) -> OnboardingReview:
        if review.status != "IN_PROGRESS":
            raise OnboardingError.for_code("ONBOARDING_REVIEW_ALREADY_STARTED", "This review is no longer active.")

        items = await self._reviews.list_checklist_items(review.id)
        unresolved_mandatory = [i for i in items if i.mandatory and i.result == "NOT_REVIEWED"]
        if unresolved_mandatory:
            raise OnboardingError.for_code(
                "ONBOARDING_CHECKLIST_INCOMPLETE",
                details={"unresolvedItems": [i.item_code for i in unresolved_mandatory]},
            )

        failed_mandatory = [i for i in items if i.mandatory and i.result == "FAIL"]
        if recommendation == "APPROVE" and failed_mandatory:
            raise OnboardingError.for_code(
                "ONBOARDING_CHECKLIST_INCOMPLETE",
                "Cannot recommend approval while mandatory checklist items have failed.",
                details={"failedItems": [i.item_code for i in failed_mandatory]},
            )

        review.status = "COMPLETED"
        review.recommendation = recommendation
        review.comments = comments
        review.completed_at = datetime.datetime.now(datetime.UTC)

        target_status = _RECOMMENDATION_TARGET.get(recommendation)
        if target_status is not None:
            await status_helper.transition(
                application, target_status, self._applications, changed_by=completed_by, comments=comments
            )

        await self._outbox.enqueue(
            OnboardingEvent.REVIEW_COMPLETED,
            {"applicationId": str(application.id), "reviewId": str(review.id), "recommendation": recommendation},
            aggregate_id=application.id,
        )
        return review


_RECOMMENDATION_TARGET = {
    "APPROVE": ApplicationStatus.PENDING_APPROVAL,
    "CONDITIONAL_APPROVAL": ApplicationStatus.PENDING_APPROVAL,
    "REJECT": ApplicationStatus.REJECTED,
    "ESCALATE": ApplicationStatus.PENDING_SECOND_LEVEL_REVIEW,
    # REQUEST_INFORMATION is handled by InformationRequestService's
    # create_request, which performs its own transition — no direct
    # status change happens here for that recommendation.
}
