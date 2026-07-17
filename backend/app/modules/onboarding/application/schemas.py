"""Request/response DTOs for the Onboarding API. Same camelCase-over-the-
wire convention as Identity — see `app.core.schema_base.CamelModel`.
"""

from __future__ import annotations

import datetime
import uuid
from typing import Any

from pydantic import Field

from app.core.schema_base import CamelModel

# --- Applicant: application summary / detail (spec 8.1) --------------------


class SectionSummaryOut(CamelModel):
    code: str
    status: str


class ApplicationSummaryOut(CamelModel):
    id: uuid.UUID
    application_number: str
    applicant_type: str
    purpose: str
    status: str
    completion_percentage: int
    submitted_at: datetime.datetime | None
    current_step: str | None
    sections: list[SectionSummaryOut]


# --- Applicant: requirements (spec 8.2) -------------------------------------


class RequiredSectionOut(CamelModel):
    code: str
    mandatory: bool


class RequiredDocumentOut(CamelModel):
    document_type: str
    mandatory: bool
    requires_expiry_date: bool
    allowed_mime_types: list[str]
    maximum_file_size_bytes: int


class ApplicationRequirementsOut(CamelModel):
    required_sections: list[RequiredSectionOut]
    required_documents: list[RequiredDocumentOut]


# --- Applicant: completeness (spec 8.3) -------------------------------------


class MissingFieldOut(CamelModel):
    section: str
    field: str


class MissingDocumentOut(CamelModel):
    document_type: str


class CompletenessOut(CamelModel):
    complete: bool
    completion_percentage: int
    missing_fields: list[MissingFieldOut]
    missing_documents: list[MissingDocumentOut]
    invalid_documents: list[MissingDocumentOut]
    expired_documents: list[MissingDocumentOut]


# --- Applicant: update section (spec 8.4) -----------------------------------


class UpdateSectionRequest(CamelModel):
    """The section body genuinely varies by applicant type and section
    (spec: "The section body depends on the applicant type and section"),
    so it's accepted as an open field bag here and validated by
    `application_service.SECTION_VALIDATORS` rather than a fixed schema
    per section — see that module.
    """

    model_config = CamelModel.model_config | {"extra": "allow"}


# --- Applicant: submit / withdraw (spec 8.5, 8.6) ---------------------------


class SubmitApplicationRequest(CamelModel):
    declaration_accepted: bool
    information_accuracy_confirmed: bool
    verification_consent_accepted: bool
    submission_version: int


class SubmitApplicationResponse(CamelModel):
    application_id: uuid.UUID
    application_number: str
    status: str
    submitted_at: datetime.datetime


class WithdrawApplicationRequest(CamelModel):
    reason: str


# --- Applicant: information requests (spec 8.7-8.9) -------------------------


class InformationRequestItemOut(CamelModel):
    id: uuid.UUID
    item_type: str
    document_type: str | None
    field_name: str | None
    instruction: str
    status: str


class InformationRequestOut(CamelModel):
    id: uuid.UUID
    reason_code: str
    message: str
    status: str
    response_due_date: datetime.date | None
    created_at: datetime.datetime
    items: list[InformationRequestItemOut]


class RespondToInformationRequestRequest(CamelModel):
    message: str | None = None
    document_ids: list[uuid.UUID] = Field(default_factory=list)
    updated_fields: list[str] = Field(default_factory=list)


class ResubmitApplicationRequest(CamelModel):
    information_request_id: uuid.UUID
    information_accuracy_confirmed: bool


# --- Documents (spec 9) ------------------------------------------------------


class CreateUploadRequestRequest(CamelModel):
    document_type: str
    file_name: str
    mime_type: str
    file_size: int


class CreateUploadRequestResponse(CamelModel):
    application_document_id: uuid.UUID
    document_id: uuid.UUID
    upload_url: str
    expires_at: datetime.datetime


class ConfirmUploadRequest(CamelModel):
    checksum: str
    document_number: str | None = None
    issuing_authority: str | None = None
    issuing_country: str | None = None
    issue_date: datetime.date | None = None
    expiry_date: datetime.date | None = None


class ApplicationDocumentOut(CamelModel):
    id: uuid.UUID
    document_id: uuid.UUID
    document_type: str
    document_number: str | None
    issuing_authority: str | None
    issue_date: datetime.date | None
    expiry_date: datetime.date | None
    processing_status: str
    review_status: str
    current_version: bool


# --- Back-office: search (spec 11.1) -----------------------------------------


class ApplicationSearchResultOut(CamelModel):
    application_id: uuid.UUID
    application_number: str
    applicant_type: str
    status: str
    completion_percentage: int
    submitted_at: datetime.datetime | None
    assigned_reviewer: uuid.UUID | None
    service_level_due_at: datetime.datetime | None


class PagedApplicationsOut(CamelModel):
    content: list[ApplicationSearchResultOut]
    page: int
    size: int
    total_elements: int
    total_pages: int


# --- Back-office: application detail (spec 11.2) -----------------------------


class StatusHistoryEntryOut(CamelModel):
    previous_status: str | None
    new_status: str
    changed_by: uuid.UUID | None
    reason_code: str | None
    comments: str | None
    created_at: datetime.datetime


class AssignmentOut(CamelModel):
    id: uuid.UUID
    reviewer_id: uuid.UUID
    assignment_type: str
    assigned_at: datetime.datetime
    active: bool


class DecisionOut(CamelModel):
    id: uuid.UUID
    decision_type: str
    decision_by: uuid.UUID
    decision_comments: str | None
    reason_code: str | None
    approval_valid_until: datetime.datetime | None
    conditions: list[dict] | None
    created_at: datetime.datetime


class RiskFlagOut(CamelModel):
    id: uuid.UUID
    flag_code: str
    risk_level: str
    description: str
    status: str
    raised_at: datetime.datetime
    resolved_at: datetime.datetime | None


class NoteOut(CamelModel):
    id: uuid.UUID
    author_id: uuid.UUID
    content: str
    created_at: datetime.datetime


class ApplicationDetailOut(CamelModel):
    application: ApplicationSummaryOut
    parties: list[dict]
    documents: list[ApplicationDocumentOut]
    assignments: list[AssignmentOut]
    status_history: list[StatusHistoryEntryOut]
    decisions: list[DecisionOut]
    risk_flags: list[RiskFlagOut]
    notes: list[NoteOut]


# --- Back-office: assignment (spec 12) ----------------------------------------


class AssignApplicationRequest(CamelModel):
    reviewer_id: uuid.UUID
    assignment_type: str = "PRIMARY_REVIEW"
    reason: str | None = None


class ReassignApplicationRequest(CamelModel):
    new_reviewer_id: uuid.UUID
    reason: str


class ReleaseApplicationRequest(CamelModel):
    reason: str | None = None


# --- Back-office: review (spec 13) --------------------------------------------


class StartReviewRequest(CamelModel):
    review_type: str


class ChecklistItemOut(CamelModel):
    id: uuid.UUID
    item_code: str
    item_description: str
    mandatory: bool
    result: str
    comments: str | None
    evidence_reference: str | None


class UpdateChecklistItemRequest(CamelModel):
    result: str
    comments: str | None = None
    evidence_reference: str | None = None


class ReviewDocumentRequest(CamelModel):
    decision: str
    comments: str | None = None
    verification_method: str | None = None
    verified_document_number: str | None = None
    verified_expiry_date: datetime.date | None = None


class CompleteReviewRequest(CamelModel):
    recommendation: str
    comments: str | None = None


class ReviewOut(CamelModel):
    id: uuid.UUID
    review_type: str
    status: str
    recommendation: str | None
    comments: str | None
    started_at: datetime.datetime
    completed_at: datetime.datetime | None
    checklist_items: list[ChecklistItemOut]


# --- Back-office: verification checks (spec 14) --------------------------------


class CreateVerificationCheckRequest(CamelModel):
    check_type: str
    provider: str
    subject_reference: str | None = None


class CompleteVerificationCheckRequest(CamelModel):
    result: str
    external_reference: str | None = None
    verified_data: dict[str, Any] = Field(default_factory=dict)
    comments: str | None = None


class VerificationCheckOut(CamelModel):
    id: uuid.UUID
    check_type: str
    provider: str
    subject_reference: str | None
    status: str
    result: str | None
    verified_data: dict | None
    initiated_at: datetime.datetime
    completed_at: datetime.datetime | None


# --- Back-office: information requests (spec 15) --------------------------------


class InformationRequestItemIn(CamelModel):
    item_type: str
    document_type: str | None = None
    instruction: str


class CreateInformationRequestRequest(CamelModel):
    reason_code: str
    message: str
    response_due_date: datetime.date | None = None
    items: list[InformationRequestItemIn] = Field(default_factory=list)


# --- Back-office: decisions (spec 16) --------------------------------------------


class ApprovalConditionIn(CamelModel):
    code: str
    description: str
    due_date: datetime.date | None = None
    blocking_after_due_date: bool = False


class ApproveApplicationRequest(CamelModel):
    decision_comments: str | None = None
    approval_valid_until: datetime.datetime | None = None
    conditions: list[ApprovalConditionIn] = Field(default_factory=list)


class ConditionallyApproveApplicationRequest(CamelModel):
    decision_comments: str | None = None
    approval_valid_until: datetime.datetime | None = None
    conditions: list[ApprovalConditionIn] = Field(default_factory=list)


class RejectApplicationRequest(CamelModel):
    reason_code: str
    decision_comments: str
    allow_new_application: bool = True
    cooling_off_period_days: int | None = None


class SuspendApplicationRequest(CamelModel):
    reason_code: str
    comments: str | None = None
    effective_immediately: bool = True


# --- Risk flags -----------------------------------------------------------------


class RaiseRiskFlagRequest(CamelModel):
    flag_code: str
    risk_level: str
    description: str


class ResolveRiskFlagRequest(CamelModel):
    status: str  # RESOLVED | ACCEPTED | DISMISSED
    resolution_comments: str
    evidence_reference: str | None = None


class AddNoteRequest(CamelModel):
    content: str
