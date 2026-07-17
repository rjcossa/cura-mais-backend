"""Application status workflow (spec section 6).

Every status change must go through `assert_transition_allowed` —
application services must never set `application.status` directly (spec:
"Controllers and repositories must not directly set arbitrary
statuses"). `OnboardingApplication.transition_to()` (domain/models.py)
is the only place that actually mutates the column, and it calls this
first.

Section 6.2 gives an explicit "Allowed transitions" list for 8 of the 16
statuses (DRAFT, SUBMITTED, QUEUED, UNDER_REVIEW,
ADDITIONAL_INFORMATION_REQUIRED, RESUBMITTED, PENDING_APPROVAL, APPROVED).
The remaining statuses are inferred from the section 6.1 flow diagram and
the surrounding functional sections (17 suspension/reinstatement, 18
expiry, 16.3 conditional approval) — each inference is commented at the
point it's made. Administrative corrections (spec 16.5) deliberately
bypass this table entirely; they're a separately-authorised, exceptional
operation, not a normal workflow edge (see `decision_service.py`).
"""

from __future__ import annotations

from app.modules.onboarding.domain.enums import ApplicationStatus as S
from app.modules.onboarding.domain.exceptions import OnboardingError

ALLOWED_TRANSITIONS: dict[S, frozenset[S]] = {
    # --- Explicitly given in spec 6.2 -----------------------------------
    S.DRAFT: frozenset({S.SUBMITTED, S.WITHDRAWN, S.CANCELLED}),
    S.SUBMITTED: frozenset({S.QUEUED, S.UNDER_REVIEW, S.WITHDRAWN}),
    S.QUEUED: frozenset({S.UNDER_REVIEW, S.WITHDRAWN, S.CANCELLED}),
    S.UNDER_REVIEW: frozenset(
        {
            S.ADDITIONAL_INFORMATION_REQUIRED,
            S.PENDING_SECOND_LEVEL_REVIEW,
            S.PENDING_APPROVAL,
            S.REJECTED,
            S.CANCELLED,
        }
    ),
    S.ADDITIONAL_INFORMATION_REQUIRED: frozenset({S.RESUBMITTED, S.WITHDRAWN, S.EXPIRED}),
    S.RESUBMITTED: frozenset({S.QUEUED, S.UNDER_REVIEW}),
    S.PENDING_APPROVAL: frozenset(
        {S.APPROVED, S.CONDITIONALLY_APPROVED, S.REJECTED, S.ADDITIONAL_INFORMATION_REQUIRED}
    ),
    S.APPROVED: frozenset({S.SUSPENDED, S.EXPIRED, S.REINSTATEMENT_REQUIRED}),
    # --- Inferred from the 6.1 diagram / surrounding sections -----------
    # 6.1's diagram shows second-level review feeding only into
    # PENDING_APPROVAL; kept narrow rather than guessing at a fuller set.
    S.PENDING_SECOND_LEVEL_REVIEW: frozenset({S.PENDING_APPROVAL}),
    # Not detailed beyond being a PENDING_APPROVAL outcome. Treated as
    # resolving the same way APPROVED does (17/18), plus REJECTED for
    # conditions missed by their due date (16.3's "blockingAfterDueDate").
    S.CONDITIONALLY_APPROVED: frozenset({S.APPROVED, S.SUSPENDED, S.EXPIRED, S.REJECTED}),
    # 17.2: reinstatement happens via a *new* application with
    # purpose=REINSTATEMENT rather than a further transition on this one,
    # so SUSPENDED's only forward edge on the same row is the marker
    # state that makes it eligible to start that process.
    S.SUSPENDED: frozenset({S.REINSTATEMENT_REQUIRED}),
    # Once the separate REINSTATEMENT-purpose application reaches its own
    # decision, a service call reflects that outcome back onto the
    # original (suspended) application via one of these.
    S.REINSTATEMENT_REQUIRED: frozenset({S.APPROVED, S.REJECTED, S.EXPIRED}),
    # --- Terminal ---------------------------------------------------------
    S.REJECTED: frozenset(),
    S.WITHDRAWN: frozenset(),
    S.EXPIRED: frozenset(),
    S.CANCELLED: frozenset(),
}


def is_transition_allowed(current: S, target: S) -> bool:
    return target in ALLOWED_TRANSITIONS.get(current, frozenset())


def assert_transition_allowed(current: S, target: S) -> None:
    if not is_transition_allowed(current, target):
        raise OnboardingError.for_code(
            "ONBOARDING_APPLICATION_STATE_INVALID",
            f"Cannot move an application from {current.value} to {target.value}.",
        )
