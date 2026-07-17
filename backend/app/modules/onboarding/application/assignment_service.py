"""Assignment: assign / claim / reassign / release (spec section 12).
Claim uses row-level locking (spec section 28) so two reviewers cannot
claim the same application.
"""

from __future__ import annotations

import datetime
import uuid

from app.modules.onboarding.domain.enums import ApplicationStatus
from app.modules.onboarding.domain.events import OnboardingEvent
from app.modules.onboarding.domain.exceptions import OnboardingError
from app.modules.onboarding.domain.models import OnboardingApplication, OnboardingApplicationAssignment
from app.modules.onboarding.domain.repositories import (
    ApplicationRepository,
    AssignmentRepository,
    OutboxRepository,
)
from app.modules.onboarding.infrastructure.identity_adapter import IdentityPort

_ASSIGNABLE_STATUSES = {
    ApplicationStatus.SUBMITTED.value,
    ApplicationStatus.QUEUED.value,
    ApplicationStatus.UNDER_REVIEW.value,
    ApplicationStatus.PENDING_SECOND_LEVEL_REVIEW.value,
}

# Roles eligible to review/claim/be-assigned onboarding applications.
ELIGIBLE_REVIEWER_ROLES = {"BACK_OFFICE_REVIEWER", "BACK_OFFICE_APPROVER", "PLATFORM_ADMIN"}


class AssignmentService:
    def __init__(
        self,
        application_repo: ApplicationRepository,
        assignment_repo: AssignmentRepository,
        outbox_repo: OutboxRepository,
        identity: IdentityPort,
    ) -> None:
        self._applications = application_repo
        self._assignments = assignment_repo
        self._outbox = outbox_repo
        self._identity = identity

    async def assign(
        self,
        application: OnboardingApplication,
        *,
        reviewer_id: uuid.UUID,
        assignment_type: str,
        assigned_by: uuid.UUID | None,
        reason: str | None,
    ) -> OnboardingApplicationAssignment:
        await self._assert_eligible_reviewer(reviewer_id)
        self._assert_assignable(application)

        if assignment_type == "PRIMARY_REVIEW":
            existing = await self._assignments.get_active_primary(application.id)
            if existing is not None:
                raise OnboardingError.for_code("ONBOARDING_APPLICATION_ALREADY_ASSIGNED")
            application.current_reviewer_id = reviewer_id

        assignment = OnboardingApplicationAssignment(
            application_id=application.id,
            reviewer_id=reviewer_id,
            assignment_type=assignment_type,
            assigned_by=assigned_by,
        )
        await self._assignments.add(assignment)

        await self._outbox.enqueue(
            OnboardingEvent.APPLICATION_ASSIGNED,
            {"applicationId": str(application.id), "reviewerId": str(reviewer_id), "reason": reason},
            aggregate_id=application.id,
        )
        return assignment

    async def claim(
        self, application_id: uuid.UUID, *, reviewer_id: uuid.UUID
    ) -> OnboardingApplicationAssignment:
        """Uses `SELECT ... FOR UPDATE` (spec 28's example) so two
        reviewers racing to claim the same application can't both
        succeed — the loser's transaction blocks until the winner
        commits, then re-reads a state where the app is no longer
        claimable and gets `ONBOARDING_APPLICATION_ALREADY_ASSIGNED`.
        """
        await self._assert_eligible_reviewer(reviewer_id)

        application = await self._applications.get_by_id_for_update(application_id)
        if application is None:
            raise OnboardingError.for_code("ONBOARDING_APPLICATION_NOT_FOUND")

        self._assert_assignable(application)
        existing = await self._assignments.get_active_primary(application.id)
        if existing is not None:
            raise OnboardingError.for_code("ONBOARDING_APPLICATION_ALREADY_ASSIGNED")

        application.current_reviewer_id = reviewer_id
        assignment = OnboardingApplicationAssignment(
            application_id=application.id,
            reviewer_id=reviewer_id,
            assignment_type="PRIMARY_REVIEW",
            assigned_by=reviewer_id,
        )
        await self._assignments.add(assignment)

        await self._outbox.enqueue(
            OnboardingEvent.APPLICATION_CLAIMED,
            {"applicationId": str(application.id), "reviewerId": str(reviewer_id)},
            aggregate_id=application.id,
        )
        return assignment

    async def reassign(
        self,
        application: OnboardingApplication,
        *,
        new_reviewer_id: uuid.UUID,
        reason: str,
        reassigned_by: uuid.UUID | None,
    ) -> OnboardingApplicationAssignment:
        await self._assert_eligible_reviewer(new_reviewer_id)

        current = await self._assignments.get_active_primary(application.id)
        if current is not None:
            current.active = False
            current.released_at = datetime.datetime.now(datetime.UTC)
            current.release_reason = f"Reassigned: {reason}"

        application.current_reviewer_id = new_reviewer_id
        new_assignment = OnboardingApplicationAssignment(
            application_id=application.id,
            reviewer_id=new_reviewer_id,
            assignment_type="PRIMARY_REVIEW",
            assigned_by=reassigned_by,
        )
        await self._assignments.add(new_assignment)

        await self._outbox.enqueue(
            OnboardingEvent.APPLICATION_REASSIGNED,
            {"applicationId": str(application.id), "newReviewerId": str(new_reviewer_id), "reason": reason},
            aggregate_id=application.id,
        )
        return new_assignment

    async def release(
        self, application: OnboardingApplication, *, reason: str | None, released_by: uuid.UUID | None
    ) -> None:
        current = await self._assignments.get_active_primary(application.id)
        if current is None:
            raise OnboardingError.for_code("ONBOARDING_APPLICATION_NOT_ASSIGNED")

        current.active = False
        current.released_at = datetime.datetime.now(datetime.UTC)
        current.release_reason = reason
        application.current_reviewer_id = None

    async def _assert_eligible_reviewer(self, reviewer_id: uuid.UUID) -> None:
        if not await self._identity.is_user_active(reviewer_id):
            raise OnboardingError.for_code(
                "ONBOARDING_APPROVAL_PRECONDITION_FAILED", "The reviewer's account is not active."
            )
        for role in ELIGIBLE_REVIEWER_ROLES:
            if await self._identity.has_role(reviewer_id, role):
                return
        raise OnboardingError.for_code(
            "ONBOARDING_APPROVAL_PRECONDITION_FAILED", "The user is not eligible to review onboarding applications."
        )

    @staticmethod
    def _assert_assignable(application: OnboardingApplication) -> None:
        if application.status not in _ASSIGNABLE_STATUSES:
            raise OnboardingError.for_code("ONBOARDING_APPLICATION_STATE_INVALID")
