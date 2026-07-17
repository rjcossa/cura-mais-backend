"""Approval, conditional approval, rejection, suspension, and
reinstatement (spec sections 16-17), including the maker-checker rule
enforced server-side (16.1) and asynchronous post-decision activation via
the outbox (16.2) — see `outbox_dispatcher.py`'s module docstring.
"""

from __future__ import annotations

import datetime
import uuid

from app.modules.onboarding.application import status_helper
from app.modules.onboarding.application.verification_service import VerificationService
from app.modules.onboarding.domain.enums import ApplicationStatus
from app.modules.onboarding.domain.events import OnboardingEvent, OnboardingNotification
from app.modules.onboarding.domain.exceptions import OnboardingError
from app.modules.onboarding.domain.models import OnboardingApplication, OnboardingDecision
from app.modules.onboarding.domain.repositories import (
    ApplicationDocumentRepository,
    ApplicationRepository,
    DecisionRepository,
    OutboxRepository,
    ReviewRepository,
    RiskFlagRepository,
)
from app.modules.onboarding.infrastructure.identity_adapter import IdentityPort


class DecisionService:
    def __init__(
        self,
        application_repo: ApplicationRepository,
        decision_repo: DecisionRepository,
        review_repo: ReviewRepository,
        document_repo: ApplicationDocumentRepository,
        risk_flag_repo: RiskFlagRepository,
        outbox_repo: OutboxRepository,
        identity: IdentityPort,
        verification_service: VerificationService,
    ) -> None:
        self._applications = application_repo
        self._decisions = decision_repo
        self._reviews = review_repo
        self._documents = document_repo
        self._risk_flags = risk_flag_repo
        self._outbox = outbox_repo
        self._identity = identity
        self._verification = verification_service

    # --- Approval (spec 16.2) -----------------------------------------------

    async def approve(
        self,
        application: OnboardingApplication,
        *,
        decision_comments: str | None,
        approval_valid_until: datetime.datetime | None,
        conditions: list[dict],
        approved_by: uuid.UUID,
    ) -> OnboardingDecision:
        await self._assert_approval_preconditions(application, approved_by)

        decision = OnboardingDecision(
            application_id=application.id,
            decision_type="CONDITIONALLY_APPROVED" if conditions else "APPROVED",
            decision_by=approved_by,
            decision_comments=decision_comments,
            approval_valid_until=approval_valid_until,
            conditions=conditions or None,
        )
        await self._decisions.add(decision)

        target = ApplicationStatus.CONDITIONALLY_APPROVED if conditions else ApplicationStatus.APPROVED
        await status_helper.transition(
            application, target, self._applications, changed_by=approved_by, comments=decision_comments
        )
        application.decision_at = datetime.datetime.now(datetime.UTC)
        application.approval_valid_until = approval_valid_until

        await self._lock_documents(application.id)

        await self._outbox.enqueue(
            OnboardingEvent.APPLICATION_CONDITIONALLY_APPROVED if conditions else OnboardingEvent.APPLICATION_APPROVED,
            {
                "applicationId": str(application.id),
                "applicationNumber": application.application_number,
                "applicantType": application.applicant_type,
                "applicantUserId": str(application.applicant_user_id),
                "applicantEntityId": str(application.applicant_entity_id),
                "approvalReference": application.application_number,
                "decidedBy": str(approved_by),
                "postApprovalAction": "ACTIVATE",
                "notificationCommand": (
                    OnboardingNotification.APPLICATION_CONDITIONALLY_APPROVED
                    if conditions
                    else OnboardingNotification.APPLICATION_APPROVED
                ),
                "channel": "EMAIL",
            },
            aggregate_id=application.id,
        )
        return decision

    async def _assert_approval_preconditions(
        self, application: OnboardingApplication, approver_id: uuid.UUID
    ) -> None:
        if application.status != ApplicationStatus.PENDING_APPROVAL.value:
            raise OnboardingError.for_code(
                "ONBOARDING_APPROVAL_PRECONDITION_FAILED", "The application is not pending approval."
            )

        existing_decision = await self._decisions.get_latest(application.id)
        if existing_decision is not None and existing_decision.decision_type in {
            "APPROVED",
            "CONDITIONALLY_APPROVED",
            "REJECTED",
        }:
            raise OnboardingError.for_code("ONBOARDING_DECISION_ALREADY_EXISTS")

        if not await self._identity.is_user_active(approver_id):
            raise OnboardingError.for_code("ONBOARDING_APPROVER_NOT_AUTHORISED")

        await self._assert_maker_checker(application, approver_id)

        reviews = await self._reviews.list_for_application(application.id)
        completed_reviews = [r for r in reviews if r.status == "COMPLETED"]
        if not completed_reviews:
            raise OnboardingError.for_code("ONBOARDING_REVIEW_INCOMPLETE")

        documents = await self._documents.list_current(application.id)
        not_accepted = [d for d in documents if d.review_status != "ACCEPTED"]
        if not_accepted:
            raise OnboardingError.for_code(
                "ONBOARDING_DOCUMENT_REVIEW_INCOMPLETE",
                details={"documents": [d.document_type for d in not_accepted]},
            )

        if not await self._verification.all_required_checks_successful(application.id):
            raise OnboardingError.for_code("ONBOARDING_VERIFICATION_INCOMPLETE")

        if await self._risk_flags.has_unresolved_blocking(application.id):
            raise OnboardingError.for_code("ONBOARDING_UNRESOLVED_RISK_FLAG")

        if not await self._identity.is_user_active(application.applicant_user_id):
            raise OnboardingError.for_code(
                "ONBOARDING_APPROVAL_PRECONDITION_FAILED", "The applicant's account is no longer active."
            )

    async def _assert_maker_checker(self, application: OnboardingApplication, approver_id: uuid.UUID) -> None:
        """spec 16.1: the approver must not be the applicant, the initial
        reviewer, or (strict segregation, always on here) any document
        reviewer on this application.
        """
        if approver_id == application.applicant_user_id:
            raise OnboardingError.for_code("ONBOARDING_MAKER_CHECKER_VIOLATION")

        reviews = await self._reviews.list_for_application(application.id)
        if any(r.reviewer_id == approver_id for r in reviews):
            raise OnboardingError.for_code("ONBOARDING_MAKER_CHECKER_VIOLATION")

        documents = await self._documents.list_current(application.id)
        for document in documents:
            for doc_review in await self._documents.list_reviews(document.id):
                if doc_review.reviewer_id == approver_id:
                    raise OnboardingError.for_code("ONBOARDING_MAKER_CHECKER_VIOLATION")

    async def _lock_documents(self, application_id: uuid.UUID) -> None:
        for document in await self._documents.list_current(application_id):
            document.locked_by_decision = True

    # --- Rejection (spec 16.4) -----------------------------------------------

    async def reject(
        self,
        application: OnboardingApplication,
        *,
        reason_code: str,
        decision_comments: str,
        allow_new_application: bool,
        cooling_off_period_days: int | None,
        rejected_by: uuid.UUID,
    ) -> OnboardingDecision:
        if not decision_comments:
            raise OnboardingError.for_code("ONBOARDING_REJECTION_REASON_REQUIRED")
        if application.status not in {
            ApplicationStatus.PENDING_APPROVAL.value,
            ApplicationStatus.UNDER_REVIEW.value,
        }:
            raise OnboardingError.for_code("ONBOARDING_APPROVAL_PRECONDITION_FAILED")

        await self._assert_maker_checker(application, rejected_by)

        decision = OnboardingDecision(
            application_id=application.id,
            decision_type="REJECTED",
            decision_by=rejected_by,
            decision_comments=decision_comments,
            reason_code=reason_code,
            allow_new_application=allow_new_application,
            cooling_off_period_days=cooling_off_period_days,
        )
        await self._decisions.add(decision)

        await status_helper.transition(
            application,
            ApplicationStatus.REJECTED,
            self._applications,
            changed_by=rejected_by,
            reason_code=reason_code,
            comments=decision_comments,
        )
        application.decision_at = datetime.datetime.now(datetime.UTC)

        await self._outbox.enqueue(
            OnboardingEvent.APPLICATION_REJECTED,
            {
                "applicationId": str(application.id),
                "reasonCode": reason_code,
                "notificationCommand": OnboardingNotification.APPLICATION_REJECTED,
                "channel": "EMAIL",
                "parameters": {"reasonCode": reason_code, "comments": decision_comments},
            },
            aggregate_id=application.id,
        )
        return decision

    # --- Suspension / reinstatement (spec 17) ---------------------------------

    async def suspend(
        self,
        application: OnboardingApplication,
        *,
        reason_code: str,
        comments: str | None,
        suspended_by: uuid.UUID,
    ) -> OnboardingDecision:
        if application.status not in {
            ApplicationStatus.APPROVED.value,
            ApplicationStatus.CONDITIONALLY_APPROVED.value,
        }:
            raise OnboardingError.for_code(
                "ONBOARDING_APPROVAL_PRECONDITION_FAILED", "Only approved applicants can be suspended."
            )

        decision = OnboardingDecision(
            application_id=application.id,
            decision_type="SUSPENDED",
            decision_by=suspended_by,
            decision_comments=comments,
            reason_code=reason_code,
        )
        await self._decisions.add(decision)

        await status_helper.transition(
            application,
            ApplicationStatus.SUSPENDED,
            self._applications,
            changed_by=suspended_by,
            reason_code=reason_code,
            comments=comments,
        )

        await self._outbox.enqueue(
            OnboardingEvent.APPLICANT_SUSPENDED,
            {
                "applicationId": str(application.id),
                "applicantType": application.applicant_type,
                "applicantUserId": str(application.applicant_user_id),
                "applicantEntityId": str(application.applicant_entity_id),
                "postApprovalAction": "SUSPEND",
                "reason": comments or reason_code,
                "notificationCommand": OnboardingNotification.PROVIDER_SUSPENDED,
                "channel": "EMAIL",
                "parameters": {"reasonCode": reason_code},
            },
            aggregate_id=application.id,
        )
        return decision

    async def mark_reinstatement_required(
        self, application: OnboardingApplication, *, changed_by: uuid.UUID | None
    ) -> None:
        await status_helper.transition(
            application, ApplicationStatus.REINSTATEMENT_REQUIRED, self._applications, changed_by=changed_by
        )

    async def approve_reinstatement(
        self, application: OnboardingApplication, *, approval_reference: str, approved_by: uuid.UUID
    ) -> OnboardingDecision:
        """Approves reinstatement *on the original (suspended) application*
        once its separate REINSTATEMENT-purpose application has itself
        been approved (spec 17.2-17.3).
        """
        if application.status != ApplicationStatus.REINSTATEMENT_REQUIRED.value:
            raise OnboardingError.for_code("ONBOARDING_APPROVAL_PRECONDITION_FAILED")

        decision = OnboardingDecision(
            application_id=application.id,
            decision_type="REINSTATED",
            decision_by=approved_by,
            decision_comments=f"Reinstated via {approval_reference}",
        )
        await self._decisions.add(decision)

        await status_helper.transition(
            application, ApplicationStatus.APPROVED, self._applications, changed_by=approved_by
        )

        await self._outbox.enqueue(
            OnboardingEvent.APPLICANT_REINSTATED,
            {
                "applicationId": str(application.id),
                "applicantType": application.applicant_type,
                "applicantUserId": str(application.applicant_user_id),
                "applicantEntityId": str(application.applicant_entity_id),
                "approvalReference": approval_reference,
                "postApprovalAction": "REINSTATE",
                "notificationCommand": OnboardingNotification.PROVIDER_REINSTATED,
                "channel": "EMAIL",
            },
            aggregate_id=application.id,
        )
        return decision
