"""Domain events published by the Onboarding module (spec section 22).

Same transactional-outbox pattern as Identity: written to this module's
own `event_outbox` table in the same transaction as the business change,
delivered by `app.core.outbox.OutboxDispatcher` outside any request
transaction. See `application/outbox_dispatcher.py`.
"""

from __future__ import annotations


class OnboardingEvent:
    APPLICATION_CREATED = "OnboardingApplicationCreated"
    APPLICATION_SUBMITTED = "OnboardingApplicationSubmitted"
    APPLICATION_QUEUED = "OnboardingApplicationQueued"
    APPLICATION_ASSIGNED = "OnboardingApplicationAssigned"
    APPLICATION_CLAIMED = "OnboardingApplicationClaimed"
    APPLICATION_REASSIGNED = "OnboardingApplicationReassigned"
    REVIEW_STARTED = "OnboardingReviewStarted"
    DOCUMENT_REVIEWED = "OnboardingDocumentReviewed"
    VERIFICATION_STARTED = "OnboardingVerificationStarted"
    VERIFICATION_COMPLETED = "OnboardingVerificationCompleted"
    INFORMATION_REQUESTED = "OnboardingInformationRequested"
    INFORMATION_RESPONDED = "OnboardingInformationResponded"
    APPLICATION_RESUBMITTED = "OnboardingApplicationResubmitted"
    REVIEW_COMPLETED = "OnboardingReviewCompleted"
    APPLICATION_APPROVED = "OnboardingApplicationApproved"
    APPLICATION_CONDITIONALLY_APPROVED = "OnboardingApplicationConditionallyApproved"
    APPLICATION_REJECTED = "OnboardingApplicationRejected"
    APPLICATION_WITHDRAWN = "OnboardingApplicationWithdrawn"
    APPLICANT_SUSPENDED = "OnboardingApplicantSuspended"
    APPLICANT_REINSTATED = "OnboardingApplicantReinstated"
    CREDENTIAL_EXPIRING = "OnboardingCredentialExpiring"
    CREDENTIAL_EXPIRED = "OnboardingCredentialExpired"
    REVERIFICATION_CREATED = "OnboardingReverificationCreated"
    RISK_FLAG_RAISED = "OnboardingRiskFlagRaised"
    RISK_FLAG_RESOLVED = "OnboardingRiskFlagResolved"


class OnboardingNotification:
    """Template codes requested from the (future) Notification module,
    delivered today via the same mock/SMTP adapters Identity uses
    (`app.core.notifications`) — see spec section 23.
    """

    APPLICATION_CREATED = "ONBOARDING_APPLICATION_CREATED"
    APPLICATION_SUBMITTED = "ONBOARDING_APPLICATION_SUBMITTED"
    INFORMATION_REQUESTED = "ONBOARDING_INFORMATION_REQUESTED"
    INFORMATION_REQUEST_REMINDER = "ONBOARDING_INFORMATION_REQUEST_REMINDER"
    INFORMATION_REQUEST_OVERDUE = "ONBOARDING_INFORMATION_REQUEST_OVERDUE"
    APPLICATION_APPROVED = "ONBOARDING_APPLICATION_APPROVED"
    APPLICATION_CONDITIONALLY_APPROVED = "ONBOARDING_APPLICATION_CONDITIONALLY_APPROVED"
    APPLICATION_REJECTED = "ONBOARDING_APPLICATION_REJECTED"
    CREDENTIAL_EXPIRING = "ONBOARDING_CREDENTIAL_EXPIRING"
    CREDENTIAL_EXPIRED = "ONBOARDING_CREDENTIAL_EXPIRED"
    PROVIDER_SUSPENDED = "ONBOARDING_PROVIDER_SUSPENDED"
    REVERIFICATION_REQUIRED = "ONBOARDING_REVERIFICATION_REQUIRED"
    PROVIDER_REINSTATED = "ONBOARDING_PROVIDER_REINSTATED"
