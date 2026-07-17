"""Framework-free domain enums for the Onboarding module (spec sections
3, 5, 6). Same rationale as `app.modules.identity.domain.enums`: plain
`str, Enum` classes with zero framework dependency, imported by both the
domain layer and the API layer's Pydantic schemas.
"""

from __future__ import annotations

from enum import Enum


class ApplicantType(str, Enum):
    DOCTOR = "DOCTOR"
    NUTRITIONIST = "NUTRITIONIST"
    HOSPITAL = "HOSPITAL"
    CLINIC = "CLINIC"
    PHARMACY = "PHARMACY"


class ApplicationPurpose(str, Enum):
    INITIAL_ONBOARDING = "INITIAL_ONBOARDING"
    PERIODIC_REVERIFICATION = "PERIODIC_REVERIFICATION"
    CREDENTIAL_RENEWAL = "CREDENTIAL_RENEWAL"
    PROFILE_MATERIAL_CHANGE = "PROFILE_MATERIAL_CHANGE"
    REINSTATEMENT = "REINSTATEMENT"


class ApplicationStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    QUEUED = "QUEUED"
    UNDER_REVIEW = "UNDER_REVIEW"
    ADDITIONAL_INFORMATION_REQUIRED = "ADDITIONAL_INFORMATION_REQUIRED"
    RESUBMITTED = "RESUBMITTED"
    PENDING_SECOND_LEVEL_REVIEW = "PENDING_SECOND_LEVEL_REVIEW"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    CONDITIONALLY_APPROVED = "CONDITIONALLY_APPROVED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"
    EXPIRED = "EXPIRED"
    SUSPENDED = "SUSPENDED"
    REINSTATEMENT_REQUIRED = "REINSTATEMENT_REQUIRED"
    CANCELLED = "CANCELLED"


# Statuses in which an application counts as "open" for the one-open-
# application-per-(applicant, type, purpose) rule (spec 7.3).
OPEN_APPLICATION_STATUSES: frozenset[ApplicationStatus] = frozenset(
    {
        ApplicationStatus.DRAFT,
        ApplicationStatus.SUBMITTED,
        ApplicationStatus.QUEUED,
        ApplicationStatus.UNDER_REVIEW,
        ApplicationStatus.ADDITIONAL_INFORMATION_REQUIRED,
        ApplicationStatus.RESUBMITTED,
        ApplicationStatus.PENDING_SECOND_LEVEL_REVIEW,
        ApplicationStatus.PENDING_APPROVAL,
    }
)

# Statuses in which the application content (sections/documents) may
# still be edited by the applicant.
EDITABLE_STATUSES: frozenset[ApplicationStatus] = frozenset(
    {
        ApplicationStatus.DRAFT,
        ApplicationStatus.ADDITIONAL_INFORMATION_REQUIRED,
        ApplicationStatus.RESUBMITTED,
    }
)


class PartyType(str, Enum):
    PRIMARY_APPLICANT = "PRIMARY_APPLICANT"
    AUTHORISED_REPRESENTATIVE = "AUTHORISED_REPRESENTATIVE"
    DIRECTOR = "DIRECTOR"
    OWNER = "OWNER"
    BENEFICIAL_OWNER = "BENEFICIAL_OWNER"
    RESPONSIBLE_PROFESSIONAL = "RESPONSIBLE_PROFESSIONAL"
    ADMINISTRATOR = "ADMINISTRATOR"


class SectionStatus(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETE = "COMPLETE"
    INVALID = "INVALID"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class DocumentProcessingStatus(str, Enum):
    PENDING_UPLOAD = "PENDING_UPLOAD"
    UPLOADED = "UPLOADED"
    PROCESSING = "PROCESSING"
    AVAILABLE = "AVAILABLE"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"
    DELETED = "DELETED"


class DocumentReviewStatus(str, Enum):
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    CLARIFICATION_REQUIRED = "CLARIFICATION_REQUIRED"
    EXPIRED = "EXPIRED"
    UNVERIFIABLE = "UNVERIFIABLE"


class AssignmentType(str, Enum):
    PRIMARY_REVIEW = "PRIMARY_REVIEW"
    SECOND_LEVEL_REVIEW = "SECOND_LEVEL_REVIEW"
    COMPLIANCE_REVIEW = "COMPLIANCE_REVIEW"
    FINAL_APPROVAL = "FINAL_APPROVAL"


class ReviewType(str, Enum):
    INITIAL_REVIEW = "INITIAL_REVIEW"
    DOCUMENT_REVIEW = "DOCUMENT_REVIEW"
    COMPLIANCE_REVIEW = "COMPLIANCE_REVIEW"
    PROFESSIONAL_VERIFICATION = "PROFESSIONAL_VERIFICATION"
    SECOND_LEVEL_REVIEW = "SECOND_LEVEL_REVIEW"
    FINAL_APPROVAL = "FINAL_APPROVAL"
    REVERIFICATION_REVIEW = "REVERIFICATION_REVIEW"


class ReviewStatus(str, Enum):
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class ReviewRecommendation(str, Enum):
    APPROVE = "APPROVE"
    CONDITIONAL_APPROVAL = "CONDITIONAL_APPROVAL"
    REJECT = "REJECT"
    REQUEST_INFORMATION = "REQUEST_INFORMATION"
    ESCALATE = "ESCALATE"


class ChecklistResult(str, Enum):
    NOT_REVIEWED = "NOT_REVIEWED"
    PASS_ = "PASS"  # `PASS` shadows a Python keyword-ish builtin pattern; value is still "PASS"
    FAIL = "FAIL"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    CLARIFICATION_REQUIRED = "CLARIFICATION_REQUIRED"


class DocumentReviewDecision(str, Enum):
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    CLARIFICATION_REQUIRED = "CLARIFICATION_REQUIRED"
    EXPIRED = "EXPIRED"
    UNVERIFIABLE = "UNVERIFIABLE"


class VerificationCheckStatus(str, Enum):
    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class VerificationCheckResult(str, Enum):
    MATCH = "MATCH"
    PARTIAL_MATCH = "PARTIAL_MATCH"
    NO_MATCH = "NO_MATCH"
    NOT_FOUND = "NOT_FOUND"
    UNAVAILABLE = "UNAVAILABLE"
    FAILED = "FAILED"
    MANUAL_REVIEW_REQUIRED = "MANUAL_REVIEW_REQUIRED"


class InformationRequestStatus(str, Enum):
    OPEN = "OPEN"
    PARTIALLY_RESPONDED = "PARTIALLY_RESPONDED"
    RESPONDED = "RESPONDED"
    SATISFIED = "SATISFIED"
    CLOSED = "CLOSED"
    OVERDUE = "OVERDUE"
    CANCELLED = "CANCELLED"


class InformationRequestItemType(str, Enum):
    DOCUMENT = "DOCUMENT"
    FIELD = "FIELD"
    DECLARATION = "DECLARATION"
    EXPLANATION = "EXPLANATION"
    OTHER = "OTHER"


class InformationRequestItemStatus(str, Enum):
    OPEN = "OPEN"
    RESPONDED = "RESPONDED"
    SATISFIED = "SATISFIED"
    REJECTED = "REJECTED"


class DecisionType(str, Enum):
    APPROVED = "APPROVED"
    CONDITIONALLY_APPROVED = "CONDITIONALLY_APPROVED"
    REJECTED = "REJECTED"
    SUSPENDED = "SUSPENDED"
    REINSTATED = "REINSTATED"
    EXPIRED = "EXPIRED"
    ADMINISTRATIVE_CORRECTION = "ADMINISTRATIVE_CORRECTION"


class RiskLevel(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


# Risk levels that block approval (spec 19.3: "High or critical unresolved
# flags block approval").
BLOCKING_RISK_LEVELS: frozenset[RiskLevel] = frozenset({RiskLevel.HIGH, RiskLevel.CRITICAL})


class RiskFlagStatus(str, Enum):
    OPEN = "OPEN"
    UNDER_REVIEW = "UNDER_REVIEW"
    RESOLVED = "RESOLVED"
    ACCEPTED = "ACCEPTED"
    DISMISSED = "DISMISSED"


RESOLVED_RISK_STATUSES: frozenset[RiskFlagStatus] = frozenset(
    {RiskFlagStatus.RESOLVED, RiskFlagStatus.ACCEPTED, RiskFlagStatus.DISMISSED}
)
