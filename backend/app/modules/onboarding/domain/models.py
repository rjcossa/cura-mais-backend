"""SQLAlchemy ORM models for every table owned by the Onboarding module
(spec sections 2.2, 20).

Three tables are listed as owned (spec 2.2) but have no explicit DDL in
spec section 20: `onboarding_review_checklists`,
`onboarding_reverification_cases`, and `onboarding_application_notes`.
Each is designed here to fit the surrounding spec text (13.2, 18.2, and
the "Notes" field in 11.2's application-detail response respectively) —
flagged individually below. Every other table is transcribed as closely
to the given DDL as the ORM allows (same columns, constraints, indexes).

No ORM `relationship()` graph, same reasoning as Identity's models.py:
repositories query with explicit `select().join(...)` where needed, and
each model stays a self-contained mapping to its table.
"""

from __future__ import annotations

import datetime
import uuid

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.core.model_helpers import uuid_pk


class OnboardingApplication(Base):
    __tablename__ = "onboarding_applications"

    id: Mapped[uuid.UUID] = uuid_pk()

    application_number: Mapped[str] = mapped_column(String(60), nullable=False, unique=True)

    applicant_type: Mapped[str] = mapped_column(String(50), nullable=False)
    applicant_user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    applicant_entity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)

    application_purpose: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(60), nullable=False, default="DRAFT")

    completion_percentage: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    submission_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    current_reviewer_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    current_approval_level: Mapped[int | None] = mapped_column(Integer)

    submitted_at: Mapped[datetime.datetime | None] = mapped_column()
    queued_at: Mapped[datetime.datetime | None] = mapped_column()
    review_started_at: Mapped[datetime.datetime | None] = mapped_column()
    decision_at: Mapped[datetime.datetime | None] = mapped_column()

    approval_valid_until: Mapped[datetime.datetime | None] = mapped_column()
    expires_at: Mapped[datetime.datetime | None] = mapped_column()

    service_level_due_at: Mapped[datetime.datetime | None] = mapped_column()
    service_level_paused_at: Mapped[datetime.datetime | None] = mapped_column()
    total_paused_seconds: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)

    created_at: Mapped[datetime.datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime.datetime] = mapped_column(server_default=func.now(), onupdate=func.now())

    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))

    version: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)

    __mapper_args__ = {"version_id_col": version}

    __table_args__ = (
        CheckConstraint(
            "applicant_type IN ('DOCTOR','NUTRITIONIST','HOSPITAL','CLINIC','PHARMACY')",
            name="onboarding_applicant_type_check",
        ),
        CheckConstraint(
            "application_purpose IN ("
            "'INITIAL_ONBOARDING','PERIODIC_REVERIFICATION','CREDENTIAL_RENEWAL',"
            "'PROFILE_MATERIAL_CHANGE','REINSTATEMENT')",
            name="onboarding_purpose_check",
        ),
        CheckConstraint(
            "status IN ("
            "'DRAFT','SUBMITTED','QUEUED','UNDER_REVIEW','ADDITIONAL_INFORMATION_REQUIRED',"
            "'RESUBMITTED','PENDING_SECOND_LEVEL_REVIEW','PENDING_APPROVAL','APPROVED',"
            "'CONDITIONALLY_APPROVED','REJECTED','WITHDRAWN','EXPIRED','SUSPENDED',"
            "'REINSTATEMENT_REQUIRED','CANCELLED')",
            name="onboarding_status_check",
        ),
        CheckConstraint("completion_percentage BETWEEN 0 AND 100", name="onboarding_completion_check"),
        Index("ix_onboarding_applications_status", "status", "submitted_at"),
        Index("ix_onboarding_applications_applicant", "applicant_type", "applicant_entity_id"),
        Index("ix_onboarding_applications_reviewer", "current_reviewer_id", "status"),
        Index(
            "ix_onboarding_applications_sla",
            "service_level_due_at",
            postgresql_where=text("status IN ('SUBMITTED','QUEUED','UNDER_REVIEW','PENDING_APPROVAL')"),
        ),
        Index(
            "ux_onboarding_open_application",
            "applicant_type",
            "applicant_entity_id",
            "application_purpose",
            unique=True,
            postgresql_where=text(
                "status IN ('DRAFT','SUBMITTED','QUEUED','UNDER_REVIEW',"
                "'ADDITIONAL_INFORMATION_REQUIRED','RESUBMITTED',"
                "'PENDING_SECOND_LEVEL_REVIEW','PENDING_APPROVAL')"
            ),
        ),
    )


class OnboardingApplicationParty(Base):
    __tablename__ = "onboarding_application_parties"

    id: Mapped[uuid.UUID] = uuid_pk()
    application_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("onboarding_applications.id"), nullable=False
    )

    party_type: Mapped[str] = mapped_column(String(60), nullable=False)

    related_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    related_entity_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))

    full_name: Mapped[str | None] = mapped_column(String(255))
    organisation_name: Mapped[str | None] = mapped_column(String(255))

    identity_number_encrypted: Mapped[str | None] = mapped_column(Text)
    identity_number_hash: Mapped[str | None] = mapped_column(String(255))

    ownership_percentage: Mapped[float | None] = mapped_column(Numeric(7, 4))

    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    created_at: Mapped[datetime.datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime.datetime] = mapped_column(server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        CheckConstraint(
            "party_type IN ('PRIMARY_APPLICANT','AUTHORISED_REPRESENTATIVE','DIRECTOR','OWNER',"
            "'BENEFICIAL_OWNER','RESPONSIBLE_PROFESSIONAL','ADMINISTRATOR')",
            name="onboarding_party_type_check",
        ),
        Index("ix_onboarding_parties_application", "application_id"),
    )


class OnboardingApplicationSection(Base):
    __tablename__ = "onboarding_application_sections"

    id: Mapped[uuid.UUID] = uuid_pk()
    application_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("onboarding_applications.id"), nullable=False
    )

    section_code: Mapped[str] = mapped_column(String(100), nullable=False)

    status: Mapped[str] = mapped_column(String(30), nullable=False, default="NOT_STARTED")

    # Not in the spec's DDL for this table — spec 8.4 explicitly permits
    # Onboarding to "delegate the detailed profile update to the Provider
    # module and retain only the section completion state." Since a real
    # Provider module doesn't exist yet (see app/shared/provider), this
    # column holds that data locally so the section/completeness/
    # submission endpoints are actually functional today. When a real
    # Provider module ships, this becomes a cache of what Provider owns
    # rather than the source of truth — no other column here changes.
    data: Mapped[dict | None] = mapped_column(JSONB)

    completion_percentage: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    validation_errors: Mapped[dict | None] = mapped_column(JSONB)

    completed_at: Mapped[datetime.datetime | None] = mapped_column()
    updated_at: Mapped[datetime.datetime] = mapped_column(server_default=func.now(), onupdate=func.now())

    version: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)

    __mapper_args__ = {"version_id_col": version}

    __table_args__ = (
        CheckConstraint(
            "status IN ('NOT_STARTED','IN_PROGRESS','COMPLETE','INVALID','NOT_APPLICABLE')",
            name="onboarding_section_status_check",
        ),
        UniqueConstraint("application_id", "section_code", name="ux_onboarding_application_section"),
        Index("ix_onboarding_sections_application", "application_id"),
    )


class OnboardingApplicationStatusHistory(Base):
    __tablename__ = "onboarding_application_status_history"

    id: Mapped[uuid.UUID] = uuid_pk()
    application_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("onboarding_applications.id"), nullable=False
    )

    previous_status: Mapped[str | None] = mapped_column(String(60))
    new_status: Mapped[str] = mapped_column(String(60), nullable=False)

    changed_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    reason_code: Mapped[str | None] = mapped_column(String(100))
    comments: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime.datetime] = mapped_column(server_default=func.now())

    __table_args__ = (Index("ix_onboarding_status_history", "application_id", "created_at"),)


class OnboardingApplicationAssignment(Base):
    __tablename__ = "onboarding_application_assignments"

    id: Mapped[uuid.UUID] = uuid_pk()
    application_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("onboarding_applications.id"), nullable=False
    )

    reviewer_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    assignment_type: Mapped[str] = mapped_column(String(50), nullable=False)

    assigned_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    assigned_at: Mapped[datetime.datetime] = mapped_column(server_default=func.now())

    released_at: Mapped[datetime.datetime | None] = mapped_column()
    release_reason: Mapped[str | None] = mapped_column(String(500))

    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    __table_args__ = (
        CheckConstraint(
            "assignment_type IN ('PRIMARY_REVIEW','SECOND_LEVEL_REVIEW','COMPLIANCE_REVIEW','FINAL_APPROVAL')",
            name="onboarding_assignment_type_check",
        ),
        Index("ix_onboarding_assignments_application", "application_id", "active"),
        Index("ix_onboarding_assignments_reviewer", "reviewer_id", "active"),
        Index(
            "ux_onboarding_active_primary_assignment",
            "application_id",
            unique=True,
            postgresql_where=text("active = TRUE AND assignment_type = 'PRIMARY_REVIEW'"),
        ),
    )


class OnboardingDocumentRequirement(Base):
    __tablename__ = "onboarding_document_requirements"

    id: Mapped[uuid.UUID] = uuid_pk()

    applicant_type: Mapped[str] = mapped_column(String(50), nullable=False)
    application_purpose: Mapped[str | None] = mapped_column(String(50))

    country_code: Mapped[str | None] = mapped_column(String(2))
    speciality_code: Mapped[str | None] = mapped_column(String(100))

    document_type: Mapped[str] = mapped_column(String(100), nullable=False)

    mandatory: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    minimum_quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    maximum_quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    requires_issue_date: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    requires_expiry_date: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    requires_document_number: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    requires_issuing_authority: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    allowed_mime_types: Mapped[list] = mapped_column(JSONB, nullable=False)
    maximum_file_size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)

    effective_from: Mapped[datetime.datetime] = mapped_column(nullable=False)
    effective_until: Mapped[datetime.datetime | None] = mapped_column()

    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    created_at: Mapped[datetime.datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime.datetime] = mapped_column(server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("ix_onboarding_document_requirements", "applicant_type", "application_purpose", "active"),
    )


class OnboardingApplicationDocument(Base):
    __tablename__ = "onboarding_application_documents"

    id: Mapped[uuid.UUID] = uuid_pk()
    application_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("onboarding_applications.id"), nullable=False
    )

    document_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)

    document_type: Mapped[str] = mapped_column(String(100), nullable=False)

    document_number: Mapped[str | None] = mapped_column(String(180))
    issuing_authority: Mapped[str | None] = mapped_column(String(255))
    issuing_country: Mapped[str | None] = mapped_column(String(2))

    issue_date: Mapped[datetime.date | None] = mapped_column(Date)
    expiry_date: Mapped[datetime.date | None] = mapped_column(Date)

    processing_status: Mapped[str] = mapped_column(String(40), nullable=False, default="PENDING_UPLOAD")
    review_status: Mapped[str] = mapped_column(String(40), nullable=False, default="PENDING")

    satisfies_requirement_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("onboarding_document_requirements.id")
    )

    current_version: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    supersedes_application_document_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("onboarding_application_documents.id")
    )

    locked_by_decision: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    created_at: Mapped[datetime.datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime.datetime] = mapped_column(server_default=func.now(), onupdate=func.now())
    deleted_at: Mapped[datetime.datetime | None] = mapped_column()

    __table_args__ = (
        CheckConstraint(
            "processing_status IN ('PENDING_UPLOAD','UPLOADED','PROCESSING','AVAILABLE','REJECTED',"
            "'SUPERSEDED','DELETED')",
            name="onboarding_document_processing_check",
        ),
        CheckConstraint(
            "review_status IN ('PENDING','ACCEPTED','REJECTED','CLARIFICATION_REQUIRED','EXPIRED','UNVERIFIABLE')",
            name="onboarding_document_review_check",
        ),
        CheckConstraint(
            "expiry_date IS NULL OR issue_date IS NULL OR expiry_date >= issue_date",
            name="onboarding_document_dates_check",
        ),
        Index("ix_onboarding_documents_application", "application_id", "current_version"),
        Index(
            "ix_onboarding_documents_expiry",
            "expiry_date",
            postgresql_where=text("expiry_date IS NOT NULL AND current_version = TRUE"),
        ),
    )


class OnboardingReview(Base):
    __tablename__ = "onboarding_reviews"

    id: Mapped[uuid.UUID] = uuid_pk()
    application_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("onboarding_applications.id"), nullable=False
    )

    reviewer_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)

    review_type: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="IN_PROGRESS")

    recommendation: Mapped[str | None] = mapped_column(String(40))
    comments: Mapped[str | None] = mapped_column(Text)

    started_at: Mapped[datetime.datetime] = mapped_column(server_default=func.now())
    completed_at: Mapped[datetime.datetime | None] = mapped_column()

    version: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)

    __mapper_args__ = {"version_id_col": version}

    __table_args__ = (
        CheckConstraint(
            "review_type IN ('INITIAL_REVIEW','DOCUMENT_REVIEW','COMPLIANCE_REVIEW',"
            "'PROFESSIONAL_VERIFICATION','SECOND_LEVEL_REVIEW','FINAL_APPROVAL','REVERIFICATION_REVIEW')",
            name="onboarding_review_type_check",
        ),
        CheckConstraint(
            "status IN ('IN_PROGRESS','COMPLETED','CANCELLED')", name="onboarding_review_status_check"
        ),
        CheckConstraint(
            "recommendation IS NULL OR recommendation IN "
            "('APPROVE','CONDITIONAL_APPROVAL','REJECT','REQUEST_INFORMATION','ESCALATE')",
            name="onboarding_review_recommendation_check",
        ),
        Index("ix_onboarding_reviews_application", "application_id"),
        Index("ix_onboarding_reviews_reviewer", "reviewer_id", "status"),
    )


class OnboardingReviewChecklist(Base):
    """Checklist *template* (spec 13.2: "Checklists should be configurable
    by applicant type, review type, country, application purpose,
    effective date"). Not given explicit DDL in spec section 20 — only
    listed as an owned table in 2.2 — so it's designed here to hold the
    template item definitions as JSONB (`{code, description, mandatory}[]`)
    rather than a separate template-items table, since only
    `onboarding_review_checklist_items` (the per-review *instance* table)
    appears in the DDL list. When a review starts, its items are
    materialised from the matching template — see
    `application/review_service.py::start_review`.
    """

    __tablename__ = "onboarding_review_checklists"

    id: Mapped[uuid.UUID] = uuid_pk()

    applicant_type: Mapped[str] = mapped_column(String(50), nullable=False)
    review_type: Mapped[str] = mapped_column(String(50), nullable=False)
    country_code: Mapped[str | None] = mapped_column(String(2))
    application_purpose: Mapped[str | None] = mapped_column(String(50))

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    items: Mapped[list] = mapped_column(JSONB, nullable=False)  # [{code, description, mandatory}]

    effective_from: Mapped[datetime.datetime] = mapped_column(server_default=func.now())
    effective_until: Mapped[datetime.datetime | None] = mapped_column()
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    created_at: Mapped[datetime.datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime.datetime] = mapped_column(server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index(
            "ix_onboarding_checklists_lookup",
            "applicant_type",
            "review_type",
            "active",
        ),
    )


class OnboardingReviewChecklistItem(Base):
    __tablename__ = "onboarding_review_checklist_items"

    id: Mapped[uuid.UUID] = uuid_pk()
    review_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("onboarding_reviews.id"), nullable=False
    )

    item_code: Mapped[str] = mapped_column(String(120), nullable=False)
    item_description: Mapped[str] = mapped_column(String(500), nullable=False)

    mandatory: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    result: Mapped[str] = mapped_column(String(40), nullable=False, default="NOT_REVIEWED")
    comments: Mapped[str | None] = mapped_column(Text)
    evidence_reference: Mapped[str | None] = mapped_column(String(255))

    completed_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    completed_at: Mapped[datetime.datetime | None] = mapped_column()

    __table_args__ = (
        CheckConstraint(
            "result IN ('NOT_REVIEWED','PASS','FAIL','NOT_APPLICABLE','CLARIFICATION_REQUIRED')",
            name="onboarding_checklist_result_check",
        ),
        UniqueConstraint("review_id", "item_code", name="ux_onboarding_review_checklist_item"),
    )


class OnboardingDocumentReview(Base):
    __tablename__ = "onboarding_document_reviews"

    id: Mapped[uuid.UUID] = uuid_pk()
    application_document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("onboarding_application_documents.id"), nullable=False
    )

    reviewer_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)

    decision: Mapped[str] = mapped_column(String(40), nullable=False)
    verification_method: Mapped[str | None] = mapped_column(String(80))
    comments: Mapped[str | None] = mapped_column(Text)

    verified_document_number: Mapped[str | None] = mapped_column(String(180))
    verified_expiry_date: Mapped[datetime.date | None] = mapped_column(Date)
    external_reference: Mapped[str | None] = mapped_column(String(255))

    created_at: Mapped[datetime.datetime] = mapped_column(server_default=func.now())

    __table_args__ = (
        CheckConstraint(
            "decision IN ('ACCEPTED','REJECTED','CLARIFICATION_REQUIRED','EXPIRED','UNVERIFIABLE')",
            name="onboarding_document_review_decision_check",
        ),
        Index("ix_onboarding_document_reviews_document", "application_document_id", "created_at"),
    )


class OnboardingVerificationCheck(Base):
    __tablename__ = "onboarding_verification_checks"

    id: Mapped[uuid.UUID] = uuid_pk()
    application_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("onboarding_applications.id"), nullable=False
    )

    check_type: Mapped[str] = mapped_column(String(80), nullable=False)
    provider: Mapped[str] = mapped_column(String(100), nullable=False)

    subject_reference: Mapped[str | None] = mapped_column(String(255))

    status: Mapped[str] = mapped_column(String(40), nullable=False, default="PENDING")
    result: Mapped[str | None] = mapped_column(String(40))

    external_request_id: Mapped[str | None] = mapped_column(String(255))
    external_reference: Mapped[str | None] = mapped_column(String(255))

    verified_data: Mapped[dict | None] = mapped_column(JSONB)
    error_code: Mapped[str | None] = mapped_column(String(100))
    error_message: Mapped[str | None] = mapped_column(String(500))

    initiated_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    initiated_at: Mapped[datetime.datetime] = mapped_column(server_default=func.now())
    completed_at: Mapped[datetime.datetime | None] = mapped_column()

    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    next_retry_at: Mapped[datetime.datetime | None] = mapped_column()

    __table_args__ = (
        CheckConstraint(
            "status IN ('PENDING','IN_PROGRESS','COMPLETED','FAILED','CANCELLED')",
            name="onboarding_verification_status_check",
        ),
        CheckConstraint(
            "result IS NULL OR result IN "
            "('MATCH','PARTIAL_MATCH','NO_MATCH','NOT_FOUND','UNAVAILABLE','FAILED','MANUAL_REVIEW_REQUIRED')",
            name="onboarding_verification_result_check",
        ),
        Index("ix_onboarding_verification_application", "application_id"),
        Index(
            "ix_onboarding_verification_retry",
            "status",
            "next_retry_at",
            postgresql_where=text("status = 'FAILED'"),
        ),
    )


class OnboardingInformationRequest(Base):
    __tablename__ = "onboarding_information_requests"

    id: Mapped[uuid.UUID] = uuid_pk()
    application_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("onboarding_applications.id"), nullable=False
    )

    requested_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)

    reason_code: Mapped[str] = mapped_column(String(100), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)

    status: Mapped[str] = mapped_column(String(40), nullable=False, default="OPEN")
    response_due_date: Mapped[datetime.date | None] = mapped_column(Date)

    responded_at: Mapped[datetime.datetime | None] = mapped_column()
    satisfied_at: Mapped[datetime.datetime | None] = mapped_column()
    closed_at: Mapped[datetime.datetime | None] = mapped_column()

    created_at: Mapped[datetime.datetime] = mapped_column(server_default=func.now())

    __table_args__ = (
        CheckConstraint(
            "status IN ('OPEN','PARTIALLY_RESPONDED','RESPONDED','SATISFIED','CLOSED','OVERDUE','CANCELLED')",
            name="onboarding_information_request_status_check",
        ),
        Index("ix_onboarding_information_requests", "application_id", "status"),
    )


class OnboardingInformationRequestItem(Base):
    __tablename__ = "onboarding_information_request_items"

    id: Mapped[uuid.UUID] = uuid_pk()
    information_request_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("onboarding_information_requests.id"), nullable=False
    )

    item_type: Mapped[str] = mapped_column(String(40), nullable=False)

    document_type: Mapped[str | None] = mapped_column(String(100))
    field_name: Mapped[str | None] = mapped_column(String(150))
    instruction: Mapped[str] = mapped_column(Text, nullable=False)

    status: Mapped[str] = mapped_column(String(30), nullable=False, default="OPEN")

    response_reference: Mapped[str | None] = mapped_column(String(255))

    satisfied_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    satisfied_at: Mapped[datetime.datetime | None] = mapped_column()

    __table_args__ = (
        CheckConstraint(
            "item_type IN ('DOCUMENT','FIELD','DECLARATION','EXPLANATION','OTHER')",
            name="onboarding_information_item_type_check",
        ),
        CheckConstraint(
            "status IN ('OPEN','RESPONDED','SATISFIED','REJECTED')",
            name="onboarding_information_item_status_check",
        ),
        Index("ix_onboarding_information_items_request", "information_request_id"),
    )


class OnboardingDecision(Base):
    __tablename__ = "onboarding_decisions"

    id: Mapped[uuid.UUID] = uuid_pk()
    application_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("onboarding_applications.id"), nullable=False
    )

    decision_type: Mapped[str] = mapped_column(String(50), nullable=False)

    decision_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    decision_comments: Mapped[str | None] = mapped_column(Text)

    reason_code: Mapped[str | None] = mapped_column(String(100))

    approval_valid_until: Mapped[datetime.datetime | None] = mapped_column()
    allow_new_application: Mapped[bool | None] = mapped_column(Boolean)
    cooling_off_period_days: Mapped[int | None] = mapped_column(Integer)

    conditions: Mapped[list | None] = mapped_column(JSONB)

    supersedes_decision_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("onboarding_decisions.id")
    )

    created_at: Mapped[datetime.datetime] = mapped_column(server_default=func.now())

    __table_args__ = (
        CheckConstraint(
            "decision_type IN ('APPROVED','CONDITIONALLY_APPROVED','REJECTED','SUSPENDED','REINSTATED',"
            "'EXPIRED','ADMINISTRATIVE_CORRECTION')",
            name="onboarding_decision_type_check",
        ),
        Index("ix_onboarding_decisions_application", "application_id", "created_at"),
    )


class OnboardingRiskFlag(Base):
    __tablename__ = "onboarding_risk_flags"

    id: Mapped[uuid.UUID] = uuid_pk()
    application_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("onboarding_applications.id"), nullable=False
    )

    flag_code: Mapped[str] = mapped_column(String(120), nullable=False)
    risk_level: Mapped[str] = mapped_column(String(20), nullable=False)

    description: Mapped[str] = mapped_column(Text, nullable=False)

    status: Mapped[str] = mapped_column(String(30), nullable=False, default="OPEN")

    raised_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    assigned_to: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))

    resolution_comments: Mapped[str | None] = mapped_column(Text)
    evidence_reference: Mapped[str | None] = mapped_column(String(255))

    raised_at: Mapped[datetime.datetime] = mapped_column(server_default=func.now())
    resolved_at: Mapped[datetime.datetime | None] = mapped_column()

    __table_args__ = (
        CheckConstraint("risk_level IN ('LOW','MEDIUM','HIGH','CRITICAL')", name="onboarding_risk_level_check"),
        CheckConstraint(
            "status IN ('OPEN','UNDER_REVIEW','RESOLVED','ACCEPTED','DISMISSED')",
            name="onboarding_risk_status_check",
        ),
        Index("ix_onboarding_risk_application", "application_id", "status"),
    )


class OnboardingReverificationCase(Base):
    """Not given explicit DDL in spec section 20 (only listed as owned in
    2.2) — designed to fit spec 18.2's "Re-verification Case Creation"
    triggers and 18.3's material-change list.
    """

    __tablename__ = "onboarding_reverification_cases"

    id: Mapped[uuid.UUID] = uuid_pk()

    original_application_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("onboarding_applications.id"), nullable=False
    )
    resulting_application_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("onboarding_applications.id")
    )

    trigger_reason: Mapped[str] = mapped_column(String(60), nullable=False)
    trigger_details: Mapped[str | None] = mapped_column(Text)

    status: Mapped[str] = mapped_column(String(30), nullable=False, default="OPEN")

    created_at: Mapped[datetime.datetime] = mapped_column(server_default=func.now())
    resolved_at: Mapped[datetime.datetime | None] = mapped_column()

    __table_args__ = (
        CheckConstraint(
            "trigger_reason IN ('APPROACHING_EXPIRY','DOCUMENT_REPLACED','LICENCE_RENEWED',"
            "'MATERIAL_CHANGE','COMPLIANCE_REQUEST')",
            name="onboarding_reverification_trigger_check",
        ),
        CheckConstraint(
            "status IN ('OPEN','APPLICATION_CREATED','RESOLVED','CANCELLED')",
            name="onboarding_reverification_status_check",
        ),
        Index("ix_onboarding_reverification_original", "original_application_id"),
    )


class OnboardingApplicationNote(Base):
    """Not given explicit DDL in spec section 20 — designed to back the
    "Notes" field in the application-detail response (spec 11.2).
    """

    __tablename__ = "onboarding_application_notes"

    id: Mapped[uuid.UUID] = uuid_pk()
    application_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("onboarding_applications.id"), nullable=False
    )

    author_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)

    created_at: Mapped[datetime.datetime] = mapped_column(server_default=func.now())

    __table_args__ = (Index("ix_onboarding_notes_application", "application_id", "created_at"),)


class EventOutbox(Base):
    """Onboarding's own transactional outbox (spec 2.2, 22). Same shape
    and rationale as Identity's `event_outbox` — see that model's
    docstring (`app/modules/identity/domain/models.py`).
    """

    __tablename__ = "onboarding_event_outbox"

    id: Mapped[uuid.UUID] = uuid_pk()

    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    aggregate_type: Mapped[str] = mapped_column(String(100), nullable=False, default="OnboardingApplication")
    aggregate_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))

    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)

    status: Mapped[str] = mapped_column(String(20), nullable=False, default="PENDING")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime.datetime] = mapped_column(server_default=func.now())
    processed_at: Mapped[datetime.datetime | None] = mapped_column()

    __table_args__ = (
        CheckConstraint(
            "status IN ('PENDING','PROCESSING','PROCESSED','FAILED')",
            name="onboarding_event_outbox_status_check",
        ),
        Index(
            "ix_onboarding_event_outbox_pending",
            "created_at",
            postgresql_where=text("status = 'PENDING'"),
        ),
    )
