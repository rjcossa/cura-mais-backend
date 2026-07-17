"""The one place `OnboardingApplication.status` is ever assigned.

Every service that changes an application's status (submission,
assignment, review, decision, suspension...) calls `transition` rather
than setting `.status` directly — this is what spec section 6's
"Controllers and repositories must not directly set arbitrary statuses"
actually means in this codebase: one narrow, always-validated, always-
audited chokepoint.
"""

from __future__ import annotations

import uuid

from app.modules.onboarding.domain.enums import ApplicationStatus
from app.modules.onboarding.domain.models import OnboardingApplication, OnboardingApplicationStatusHistory
from app.modules.onboarding.domain.repositories import ApplicationRepository
from app.modules.onboarding.domain.workflow import assert_transition_allowed


async def transition(
    application: OnboardingApplication,
    target: ApplicationStatus,
    application_repo: ApplicationRepository,
    *,
    changed_by: uuid.UUID | None,
    reason_code: str | None = None,
    comments: str | None = None,
) -> None:
    current = ApplicationStatus(application.status)
    assert_transition_allowed(current, target)

    application.status = target.value
    await application_repo.add_status_history(
        OnboardingApplicationStatusHistory(
            application_id=application.id,
            previous_status=current.value,
            new_status=target.value,
            changed_by=changed_by,
            reason_code=reason_code,
            comments=comments,
        )
    )
