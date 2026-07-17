"""Onboarding module error codes (spec section 26) mapped to HTTP status
codes, following the exact same pattern as
`app.modules.identity.domain.exceptions.IdentityError`.
"""

from __future__ import annotations

from app.core.exceptions import AppError, ErrorField

_REGISTRY: dict[str, tuple[int, str]] = {
    # 26.1 Application
    "ONBOARDING_APPLICATION_NOT_FOUND": (404, "The application was not found."),
    "ONBOARDING_APPLICATION_ALREADY_EXISTS": (409, "An open application already exists for this applicant type and purpose."),
    "ONBOARDING_APPLICATION_STATE_INVALID": (409, "The application is not in a state that allows this action."),
    "ONBOARDING_APPLICATION_NOT_EDITABLE": (409, "The application can no longer be edited."),
    "ONBOARDING_APPLICATION_ALREADY_SUBMITTED": (409, "The application has already been submitted."),
    "ONBOARDING_APPLICATION_INCOMPLETE": (422, "The application cannot be submitted because mandatory requirements are outstanding."),
    "ONBOARDING_APPLICATION_VERSION_CONFLICT": (409, "The application was modified elsewhere. Please refresh and try again."),
    "ONBOARDING_APPLICATION_WITHDRAWAL_NOT_ALLOWED": (409, "The application can no longer be withdrawn."),
    # 26.2 Document
    "ONBOARDING_DOCUMENT_TYPE_NOT_ALLOWED": (422, "This document type is not accepted for this application."),
    "ONBOARDING_DOCUMENT_REQUIRED": (422, "A required document is missing."),
    "ONBOARDING_DOCUMENT_MISSING": (422, "A required document is missing."),
    "ONBOARDING_DOCUMENT_NOT_AVAILABLE": (404, "The document is not available."),
    "ONBOARDING_DOCUMENT_PROCESSING": (409, "The document is still being processed."),
    "ONBOARDING_DOCUMENT_REJECTED": (422, "The document was rejected during review."),
    "ONBOARDING_DOCUMENT_EXPIRED": (422, "The document has expired."),
    "ONBOARDING_DOCUMENT_FILE_TOO_LARGE": (422, "The file exceeds the maximum allowed size."),
    "ONBOARDING_DOCUMENT_MIME_TYPE_NOT_ALLOWED": (422, "This file type is not accepted for this document."),
    "ONBOARDING_DOCUMENT_METADATA_INVALID": (422, "The document metadata is invalid."),
    "ONBOARDING_DOCUMENT_LOCKED": (409, "This document is locked by a completed decision and cannot be changed."),
    # 26.3 Review
    "ONBOARDING_APPLICATION_NOT_ASSIGNED": (409, "The application is not assigned to a reviewer."),
    "ONBOARDING_APPLICATION_ALREADY_ASSIGNED": (409, "The application is already assigned."),
    "ONBOARDING_REVIEW_ALREADY_STARTED": (409, "A review is already in progress for this application."),
    "ONBOARDING_REVIEW_INCOMPLETE": (409, "The review is not yet complete."),
    "ONBOARDING_CHECKLIST_INCOMPLETE": (409, "Mandatory checklist items are not yet resolved."),
    "ONBOARDING_DOCUMENT_REVIEW_INCOMPLETE": (409, "Not all documents have been reviewed."),
    "ONBOARDING_VERIFICATION_INCOMPLETE": (409, "Required verification checks have not completed successfully."),
    "ONBOARDING_UNRESOLVED_RISK_FLAG": (409, "An unresolved high or critical risk flag is blocking this action."),
    # 26.4 Decision
    "ONBOARDING_APPROVAL_PRECONDITION_FAILED": (409, "The application does not meet the preconditions for this decision."),
    "ONBOARDING_MAKER_CHECKER_VIOLATION": (403, "The approver must be different from the reviewer(s) on this application."),
    "ONBOARDING_DECISION_ALREADY_EXISTS": (409, "A final decision already exists for this application."),
    "ONBOARDING_APPROVER_NOT_AUTHORISED": (403, "You are not authorised to approve this application."),
    "ONBOARDING_REJECTION_REASON_REQUIRED": (422, "A rejection reason is required."),
    "ONBOARDING_CONDITION_INVALID": (422, "One or more approval conditions are invalid."),
    # 26.5 Information request
    "ONBOARDING_INFORMATION_REQUEST_NOT_FOUND": (404, "The information request was not found."),
    "ONBOARDING_INFORMATION_REQUEST_CLOSED": (409, "This information request is closed."),
    "ONBOARDING_INFORMATION_REQUEST_INCOMPLETE": (409, "Not all mandatory information request items have been satisfied."),
    "ONBOARDING_INFORMATION_REQUEST_RESPONSE_OVERDUE": (409, "The response window for this information request has passed."),
    # Misc / cross-cutting
    "ONBOARDING_PARTY_NOT_FOUND": (404, "The application party was not found."),
    "ONBOARDING_RISK_FLAG_NOT_FOUND": (404, "The risk flag was not found."),
    "ONBOARDING_VERIFICATION_CHECK_NOT_FOUND": (404, "The verification check was not found."),
}


class OnboardingError(AppError):
    @classmethod
    def for_code(
        cls,
        code: str,
        message: str | None = None,
        *,
        fields: list[ErrorField] | None = None,
        details: dict | None = None,
    ) -> OnboardingError:
        status_code, default_message = _REGISTRY.get(code, (400, "The request could not be completed."))
        return cls(
            code=code, message=message or default_message, status_code=status_code, fields=fields, details=details
        )
