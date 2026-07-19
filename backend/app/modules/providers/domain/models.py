"""SQLAlchemy ORM models for every table owned by the Providers module
(spec section 30).

Transcribed as closely to the given DDL as the ORM allows (same columns,
constraints, indexes), same approach `app.modules.onboarding.domain.models`
already documents taking for its own spec. Two deliberate additions beyond
the literal DDL, each called out at the column:

- `ProviderProfessionalRegistration.last_expiry_reminder_window_days` —
  not in spec 30.2's DDL. Added so the expiry-monitoring scheduled job
  (`application/scheduled_tasks.py`) can avoid re-sending the same
  reminder on every hourly poll tick, a gap confirmed present in
  Onboarding's own equivalent job.
- `ProviderQualification.speciality_id` gets a real foreign key to
  `medical_specialities` even though spec 30.3's DDL doesn't declare one
  (unlike `provider_specialities.speciality_id` and
  `provider_services.speciality_id`, which do) — leaving it dangling
  would just be an oversight in the source DDL, not an intentional
  design choice, given it's clearly the same conceptual reference.

`provider_tags` (spec 2.2) is not modelled — no DDL is given anywhere in
the spec, and no endpoint anywhere references it (see plan's Scope
section). `provider_languages`, `provider_affiliations`, and
`provider_profile_media` deliberately have no `version`/optimistic-lock
column and (for languages/affiliations) no `deleted_at` — matching their
DDL exactly, and matching spec 35's concurrency list, which omits all
three from the tables requiring optimistic locking.

No ORM `relationship()` graph, same reasoning as Identity/Onboarding's
models.py: repositories query with explicit `select().join(...)` where
needed, and each model stays a self-contained mapping to its table.
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


class Provider(Base):
    __tablename__ = "providers"

    id: Mapped[uuid.UUID] = uuid_pk()

    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    provider_type: Mapped[str] = mapped_column(String(50), nullable=False)

    first_name: Mapped[str] = mapped_column(String(100), nullable=False)
    middle_name: Mapped[str | None] = mapped_column(String(100))
    last_name: Mapped[str] = mapped_column(String(100), nullable=False)

    professional_title: Mapped[str | None] = mapped_column(String(50))
    display_name: Mapped[str | None] = mapped_column(String(255))
    slug: Mapped[str] = mapped_column(String(255), nullable=False)

    short_biography: Mapped[str | None] = mapped_column(String(500))
    biography: Mapped[str | None] = mapped_column(Text)

    date_of_birth: Mapped[datetime.date | None] = mapped_column(Date)
    gender: Mapped[str | None] = mapped_column(String(30))
    nationality: Mapped[str | None] = mapped_column(String(2))

    years_of_experience: Mapped[int | None] = mapped_column(Integer)

    verification_status: Mapped[str] = mapped_column(String(50), nullable=False, default="NOT_VERIFIED")
    profile_status: Mapped[str] = mapped_column(String(40), nullable=False, default="DRAFT")
    publication_status: Mapped[str] = mapped_column(String(40), nullable=False, default="UNPUBLISHED")

    profile_completion_percentage: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    approval_application_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    approval_reference: Mapped[str | None] = mapped_column(String(100))
    approval_valid_until: Mapped[datetime.datetime | None] = mapped_column()

    verified_at: Mapped[datetime.datetime | None] = mapped_column()
    activated_at: Mapped[datetime.datetime | None] = mapped_column()
    published_at: Mapped[datetime.datetime | None] = mapped_column()
    suspended_at: Mapped[datetime.datetime | None] = mapped_column()

    created_at: Mapped[datetime.datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime.datetime] = mapped_column(server_default=func.now(), onupdate=func.now())
    deleted_at: Mapped[datetime.datetime | None] = mapped_column()

    version: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)

    __mapper_args__ = {"version_id_col": version}

    __table_args__ = (
        CheckConstraint(
            "provider_type IN ('DOCTOR','NUTRITIONIST','DENTIST','PSYCHOLOGIST','PHYSIOTHERAPIST',"
            "'NURSE','PHARMACIST','LABORATORY_PROFESSIONAL','FITNESS_PROFESSIONAL','OTHER_HEALTH_PROFESSIONAL')",
            name="providers_type_check",
        ),
        CheckConstraint(
            "verification_status IN ('NOT_VERIFIED','PENDING','VERIFIED','CONDITIONALLY_VERIFIED',"
            "'REJECTED','SUSPENDED','EXPIRED','REVOKED')",
            name="providers_verification_status_check",
        ),
        CheckConstraint(
            "profile_status IN ('DRAFT','INCOMPLETE','INACTIVE','ACTIVE','SUSPENDED','DEACTIVATED','ARCHIVED')",
            name="providers_profile_status_check",
        ),
        CheckConstraint(
            "publication_status IN ('UNPUBLISHED','PUBLISHED','HIDDEN','REMOVED')",
            name="providers_publication_status_check",
        ),
        CheckConstraint(
            "years_of_experience IS NULL OR years_of_experience BETWEEN 0 AND 80",
            name="providers_experience_check",
        ),
        CheckConstraint("profile_completion_percentage BETWEEN 0 AND 100", name="providers_completion_check"),
        Index("ux_providers_user_type", "user_id", "provider_type", unique=True, postgresql_where=text("deleted_at IS NULL")),
        Index("ux_providers_slug", "slug", unique=True, postgresql_where=text("deleted_at IS NULL")),
        Index("ix_providers_status", "verification_status", "profile_status", "publication_status"),
        Index("ix_providers_type", "provider_type"),
    )


class ProviderProfessionalRegistration(Base):
    __tablename__ = "provider_professional_registrations"

    id: Mapped[uuid.UUID] = uuid_pk()
    provider_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("providers.id"), nullable=False)

    registration_type: Mapped[str] = mapped_column(String(80), nullable=False)
    registration_number: Mapped[str] = mapped_column(String(180), nullable=False)
    registration_authority: Mapped[str] = mapped_column(String(255), nullable=False)
    registration_country: Mapped[str] = mapped_column(String(2), nullable=False)

    issue_date: Mapped[datetime.date | None] = mapped_column(Date)
    expiry_date: Mapped[datetime.date | None] = mapped_column(Date)

    registration_status: Mapped[str] = mapped_column(String(40), nullable=False, default="ACTIVE")
    verification_status: Mapped[str] = mapped_column(String(40), nullable=False, default="UNVERIFIED")

    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    onboarding_application_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    verification_reference: Mapped[str | None] = mapped_column(String(255))
    verified_at: Mapped[datetime.datetime | None] = mapped_column()
    verified_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))

    decision_locked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    supersedes_registration_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("provider_professional_registrations.id")
    )

    # Not in spec 30.2's DDL — see module docstring.
    last_expiry_reminder_window_days: Mapped[int | None] = mapped_column(Integer)

    created_at: Mapped[datetime.datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime.datetime] = mapped_column(server_default=func.now(), onupdate=func.now())
    deleted_at: Mapped[datetime.datetime | None] = mapped_column()

    version: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)

    __mapper_args__ = {"version_id_col": version}

    __table_args__ = (
        CheckConstraint(
            "registration_status IN ('ACTIVE','INACTIVE','EXPIRED','SUSPENDED','REVOKED','SUPERSEDED')",
            name="provider_registration_status_check",
        ),
        CheckConstraint(
            "verification_status IN ('UNVERIFIED','PENDING','VERIFIED','REJECTED','UNVERIFIABLE')",
            name="provider_registration_verification_check",
        ),
        CheckConstraint(
            "expiry_date IS NULL OR issue_date IS NULL OR expiry_date >= issue_date",
            name="provider_registration_date_check",
        ),
        Index(
            "ux_provider_registration_reference",
            "registration_country",
            "registration_authority",
            "registration_number",
            unique=True,
            postgresql_where=text("deleted_at IS NULL AND registration_status <> 'SUPERSEDED'"),
        ),
        Index(
            "ux_provider_primary_registration",
            "provider_id",
            unique=True,
            postgresql_where=text("is_primary = TRUE AND deleted_at IS NULL AND registration_status = 'ACTIVE'"),
        ),
        Index("ix_provider_registrations_provider", "provider_id", "registration_status"),
        Index(
            "ix_provider_registrations_expiry",
            "expiry_date",
            postgresql_where=text("expiry_date IS NOT NULL AND registration_status = 'ACTIVE'"),
        ),
    )


class ProviderQualification(Base):
    __tablename__ = "provider_qualifications"

    id: Mapped[uuid.UUID] = uuid_pk()
    provider_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("providers.id"), nullable=False)

    qualification_type: Mapped[str] = mapped_column(String(60), nullable=False)
    qualification_name: Mapped[str] = mapped_column(String(255), nullable=False)

    institution_name: Mapped[str] = mapped_column(String(255), nullable=False)
    institution_country: Mapped[str | None] = mapped_column(String(2))

    start_date: Mapped[datetime.date | None] = mapped_column(Date)
    completion_date: Mapped[datetime.date | None] = mapped_column(Date)

    # See module docstring — FK added even though not declared in spec 30.3's DDL.
    speciality_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("medical_specialities.id"))

    verification_status: Mapped[str] = mapped_column(String(40), nullable=False, default="UNVERIFIED")

    onboarding_application_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    verification_reference: Mapped[str | None] = mapped_column(String(255))
    verified_at: Mapped[datetime.datetime | None] = mapped_column()
    verified_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))

    decision_locked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    supersedes_qualification_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("provider_qualifications.id")
    )

    created_at: Mapped[datetime.datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime.datetime] = mapped_column(server_default=func.now(), onupdate=func.now())
    deleted_at: Mapped[datetime.datetime | None] = mapped_column()

    version: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)

    __mapper_args__ = {"version_id_col": version}

    __table_args__ = (
        CheckConstraint(
            "qualification_type IN ('UNDERGRADUATE_DEGREE','POSTGRADUATE_DEGREE','DIPLOMA','CERTIFICATE',"
            "'BOARD_CERTIFICATION','SPECIALIST_QUALIFICATION','PROFESSIONAL_COURSE','OTHER')",
            name="provider_qualification_type_check",
        ),
        CheckConstraint(
            "verification_status IN ('UNVERIFIED','PENDING','VERIFIED','REJECTED','UNVERIFIABLE')",
            name="provider_qualification_verification_check",
        ),
        CheckConstraint(
            "completion_date IS NULL OR start_date IS NULL OR completion_date >= start_date",
            name="provider_qualification_date_check",
        ),
        Index("ix_provider_qualifications_provider", "provider_id", "verification_status"),
    )


class MedicalSpeciality(Base):
    __tablename__ = "medical_specialities"

    id: Mapped[uuid.UUID] = uuid_pk()

    code: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)

    provider_type: Mapped[str] = mapped_column(String(50), nullable=False)

    parent_speciality_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("medical_specialities.id")
    )

    requires_verified_qualification: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    created_at: Mapped[datetime.datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime.datetime] = mapped_column(server_default=func.now(), onupdate=func.now())

    __table_args__ = (Index("ix_medical_specialities_type", "provider_type", "active"),)


class ProviderSpeciality(Base):
    __tablename__ = "provider_specialities"

    id: Mapped[uuid.UUID] = uuid_pk()
    provider_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("providers.id"), nullable=False)
    speciality_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("medical_specialities.id"), nullable=False
    )

    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    years_of_experience: Mapped[int | None] = mapped_column(Integer)

    verification_status: Mapped[str] = mapped_column(String(40), nullable=False, default="UNVERIFIED")

    verified_at: Mapped[datetime.datetime | None] = mapped_column()
    verified_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))

    created_at: Mapped[datetime.datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime.datetime] = mapped_column(server_default=func.now(), onupdate=func.now())
    deleted_at: Mapped[datetime.datetime | None] = mapped_column()

    version: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)

    __mapper_args__ = {"version_id_col": version}

    __table_args__ = (
        CheckConstraint(
            "verification_status IN ('UNVERIFIED','PENDING','VERIFIED','REJECTED')",
            name="provider_speciality_verification_check",
        ),
        CheckConstraint(
            "years_of_experience IS NULL OR years_of_experience BETWEEN 0 AND 80",
            name="provider_speciality_experience_check",
        ),
        Index("ux_provider_speciality", "provider_id", "speciality_id", unique=True, postgresql_where=text("deleted_at IS NULL")),
        Index(
            "ux_provider_primary_speciality",
            "provider_id",
            unique=True,
            postgresql_where=text("is_primary = TRUE AND deleted_at IS NULL"),
        ),
        Index("ix_provider_speciality_search", "speciality_id", "verification_status"),
    )


class ProviderLanguage(Base):
    __tablename__ = "provider_languages"

    id: Mapped[uuid.UUID] = uuid_pk()
    provider_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("providers.id"), nullable=False)

    language_code: Mapped[str] = mapped_column(String(20), nullable=False)
    proficiency: Mapped[str] = mapped_column(String(30), nullable=False)

    can_consult: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    created_at: Mapped[datetime.datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime.datetime] = mapped_column(server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        CheckConstraint(
            "proficiency IN ('BASIC','INTERMEDIATE','FLUENT','NATIVE')",
            name="provider_language_proficiency_check",
        ),
        UniqueConstraint("provider_id", "language_code", name="ux_provider_language"),
        Index("ix_provider_languages_search", "language_code", "can_consult"),
    )


class ProviderService(Base):
    __tablename__ = "provider_services"

    id: Mapped[uuid.UUID] = uuid_pk()
    provider_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("providers.id"), nullable=False)

    service_code: Mapped[str] = mapped_column(String(120), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)

    speciality_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("medical_specialities.id"))

    duration_minutes: Mapped[int] = mapped_column(Integer, nullable=False)

    price: Mapped[float | None] = mapped_column(Numeric(18, 2))
    currency: Mapped[str | None] = mapped_column(String(3))

    pro_bono: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    requires_pre_screening: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    minimum_patient_age: Mapped[int | None] = mapped_column(Integer)
    maximum_patient_age: Mapped[int | None] = mapped_column(Integer)

    booking_notice_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cancellation_notice_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    status: Mapped[str] = mapped_column(String(30), nullable=False, default="DRAFT")
    publicly_visible: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    effective_from: Mapped[datetime.datetime | None] = mapped_column()
    effective_until: Mapped[datetime.datetime | None] = mapped_column()

    activated_at: Mapped[datetime.datetime | None] = mapped_column()
    deactivated_at: Mapped[datetime.datetime | None] = mapped_column()

    created_at: Mapped[datetime.datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime.datetime] = mapped_column(server_default=func.now(), onupdate=func.now())
    deleted_at: Mapped[datetime.datetime | None] = mapped_column()

    version: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)

    __mapper_args__ = {"version_id_col": version}

    __table_args__ = (
        CheckConstraint(
            "status IN ('DRAFT','ACTIVE','INACTIVE','SUSPENDED','ARCHIVED')",
            name="provider_service_status_check",
        ),
        CheckConstraint("duration_minutes BETWEEN 5 AND 480", name="provider_service_duration_check"),
        CheckConstraint(
            "pro_bono = TRUE OR (price IS NOT NULL AND price >= 0 AND currency IS NOT NULL)",
            name="provider_service_price_check",
        ),
        CheckConstraint(
            "minimum_patient_age IS NULL OR maximum_patient_age IS NULL OR maximum_patient_age >= minimum_patient_age",
            name="provider_service_age_check",
        ),
        CheckConstraint(
            "effective_until IS NULL OR effective_from IS NULL OR effective_until >= effective_from",
            name="provider_service_effective_date_check",
        ),
        Index(
            "ux_provider_service_code",
            "provider_id",
            "service_code",
            unique=True,
            postgresql_where=text("deleted_at IS NULL AND status <> 'ARCHIVED'"),
        ),
        Index("ix_provider_services_provider", "provider_id", "status"),
        Index("ix_provider_services_speciality", "speciality_id", "status"),
    )


class ProviderServiceMode(Base):
    __tablename__ = "provider_service_modes"

    provider_service_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("provider_services.id"), primary_key=True
    )
    delivery_mode: Mapped[str] = mapped_column(String(30), primary_key=True)

    created_at: Mapped[datetime.datetime] = mapped_column(server_default=func.now())

    __table_args__ = (
        CheckConstraint(
            "delivery_mode IN ('VIDEO','AUDIO','SECURE_CHAT','IN_PERSON','HOME_VISIT','GROUP_SESSION')",
            name="provider_service_mode_check",
        ),
    )


class ProviderLocation(Base):
    __tablename__ = "provider_locations"

    id: Mapped[uuid.UUID] = uuid_pk()
    provider_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("providers.id"), nullable=False)

    institution_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    department_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))

    location_type: Mapped[str] = mapped_column(String(50), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)

    address_line_1: Mapped[str | None] = mapped_column(String(255))
    address_line_2: Mapped[str | None] = mapped_column(String(255))
    city: Mapped[str | None] = mapped_column(String(120))
    province: Mapped[str | None] = mapped_column(String(120))
    postal_code: Mapped[str | None] = mapped_column(String(30))
    country_code: Mapped[str | None] = mapped_column(String(2))

    latitude: Mapped[float | None] = mapped_column(Numeric(9, 6))
    longitude: Mapped[float | None] = mapped_column(Numeric(9, 6))

    contact_number: Mapped[str | None] = mapped_column(String(30))

    wheelchair_accessible: Mapped[bool | None] = mapped_column(Boolean)
    parking_available: Mapped[bool | None] = mapped_column(Boolean)

    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    created_at: Mapped[datetime.datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime.datetime] = mapped_column(server_default=func.now(), onupdate=func.now())
    deleted_at: Mapped[datetime.datetime | None] = mapped_column()

    version: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)

    __mapper_args__ = {"version_id_col": version}

    __table_args__ = (
        CheckConstraint(
            "location_type IN ('PRIVATE_PRACTICE','HOSPITAL','CLINIC','VIRTUAL','HOME_VISIT_SERVICE_AREA','OTHER')",
            name="provider_location_type_check",
        ),
        CheckConstraint("latitude IS NULL OR latitude BETWEEN -90 AND 90", name="provider_location_latitude_check"),
        CheckConstraint(
            "longitude IS NULL OR longitude BETWEEN -180 AND 180", name="provider_location_longitude_check"
        ),
        Index("ix_provider_locations_provider", "provider_id", "active"),
        Index("ix_provider_locations_geo", "country_code", "province", "city"),
        Index(
            "ux_provider_primary_location",
            "provider_id",
            unique=True,
            postgresql_where=text(
                "is_primary = TRUE AND active = TRUE AND deleted_at IS NULL AND location_type <> 'VIRTUAL'"
            ),
        ),
    )


class ProviderAffiliation(Base):
    __tablename__ = "provider_affiliations"

    id: Mapped[uuid.UUID] = uuid_pk()
    provider_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("providers.id"), nullable=False)

    institution_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    department_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))

    affiliation_type: Mapped[str] = mapped_column(String(50), nullable=False)
    affiliation_source: Mapped[str] = mapped_column(String(50), nullable=False)

    professional_position: Mapped[str | None] = mapped_column(String(255))

    start_date: Mapped[datetime.date | None] = mapped_column(Date)
    end_date: Mapped[datetime.date | None] = mapped_column(Date)

    status: Mapped[str] = mapped_column(String(30), nullable=False, default="PENDING")

    requested_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    confirmed_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    confirmed_at: Mapped[datetime.datetime | None] = mapped_column()

    rejection_reason: Mapped[str | None] = mapped_column(String(500))
    ended_reason: Mapped[str | None] = mapped_column(String(500))

    created_at: Mapped[datetime.datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime.datetime] = mapped_column(server_default=func.now(), onupdate=func.now())

    version: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)

    __mapper_args__ = {"version_id_col": version}

    __table_args__ = (
        CheckConstraint(
            "affiliation_type IN ('EMPLOYED','CONTRACTED','VISITING','PRACTICE_PRIVILEGES','VOLUNTEER',"
            "'OWNER','DIRECTOR','OTHER')",
            name="provider_affiliation_type_check",
        ),
        CheckConstraint(
            "affiliation_source IN ('SELF_DECLARED','INSTITUTION_REGISTERED','BACK_OFFICE_CREATED','ONBOARDING_VERIFIED')",
            name="provider_affiliation_source_check",
        ),
        CheckConstraint(
            "status IN ('PENDING','ACTIVE','REJECTED','SUSPENDED','ENDED','CANCELLED')",
            name="provider_affiliation_status_check",
        ),
        CheckConstraint(
            "end_date IS NULL OR start_date IS NULL OR end_date >= start_date",
            name="provider_affiliation_date_check",
        ),
        Index("ix_provider_affiliations_provider", "provider_id", "status"),
        Index("ix_provider_affiliations_institution", "institution_id", "status"),
    )


class ProviderProfileMedia(Base):
    __tablename__ = "provider_profile_media"

    id: Mapped[uuid.UUID] = uuid_pk()
    provider_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("providers.id"), nullable=False)
    document_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)

    media_type: Mapped[str] = mapped_column(String(50), nullable=False)

    processing_status: Mapped[str] = mapped_column(String(40), nullable=False, default="PENDING_UPLOAD")
    moderation_status: Mapped[str] = mapped_column(String(40), nullable=False, default="PENDING")

    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    created_at: Mapped[datetime.datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime.datetime] = mapped_column(server_default=func.now(), onupdate=func.now())
    deleted_at: Mapped[datetime.datetime | None] = mapped_column()

    __table_args__ = (
        CheckConstraint(
            "media_type IN ('PROFILE_PHOTO','COVER_IMAGE','INTRODUCTION_VIDEO','OTHER')",
            name="provider_media_type_check",
        ),
        CheckConstraint(
            "processing_status IN ('PENDING_UPLOAD','UPLOADED','PROCESSING','AVAILABLE','REJECTED','DELETED')",
            name="provider_media_processing_check",
        ),
        CheckConstraint(
            "moderation_status IN ('PENDING','APPROVED','REJECTED','NOT_REQUIRED')",
            name="provider_media_moderation_check",
        ),
        Index("ix_provider_profile_media", "provider_id", "media_type", "active"),
    )


class ProviderVisibilitySettings(Base):
    __tablename__ = "provider_visibility_settings"

    provider_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("providers.id"), primary_key=True)

    show_full_biography: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    show_qualifications: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    show_affiliations: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    show_locations: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    show_years_of_experience: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    show_languages: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    show_service_prices: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    allow_direct_booking: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    allow_pro_bono_discovery: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    updated_at: Mapped[datetime.datetime] = mapped_column(server_default=func.now(), onupdate=func.now())
    version: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)

    __mapper_args__ = {"version_id_col": version}


class ProviderStatusHistory(Base):
    __tablename__ = "provider_status_history"

    id: Mapped[uuid.UUID] = uuid_pk()
    provider_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("providers.id"), nullable=False)

    status_type: Mapped[str] = mapped_column(String(40), nullable=False)

    previous_status: Mapped[str | None] = mapped_column(String(50))
    new_status: Mapped[str] = mapped_column(String(50), nullable=False)

    reason_code: Mapped[str | None] = mapped_column(String(100))
    comments: Mapped[str | None] = mapped_column(Text)

    source_type: Mapped[str | None] = mapped_column(String(50))
    source_reference: Mapped[str | None] = mapped_column(String(255))

    changed_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))

    created_at: Mapped[datetime.datetime] = mapped_column(server_default=func.now())

    __table_args__ = (
        CheckConstraint(
            "status_type IN ('VERIFICATION_STATUS','PROFILE_STATUS','PUBLICATION_STATUS')",
            name="provider_status_history_type_check",
        ),
        Index("ix_provider_status_history", "provider_id", "created_at"),
    )


class ProviderPublicationHistory(Base):
    __tablename__ = "provider_publication_history"

    id: Mapped[uuid.UUID] = uuid_pk()
    provider_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("providers.id"), nullable=False)

    action: Mapped[str] = mapped_column(String(30), nullable=False)

    reason_code: Mapped[str | None] = mapped_column(String(100))
    comments: Mapped[str | None] = mapped_column(Text)

    performed_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))

    created_at: Mapped[datetime.datetime] = mapped_column(server_default=func.now())

    __table_args__ = (
        CheckConstraint(
            "action IN ('PUBLISHED','UNPUBLISHED','HIDDEN','RESTORED','REMOVED')",
            name="provider_publication_action_check",
        ),
        Index("ix_provider_publication_history", "provider_id", "created_at"),
    )


class ProviderExternalIdentifier(Base):
    __tablename__ = "provider_external_identifiers"

    id: Mapped[uuid.UUID] = uuid_pk()
    provider_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("providers.id"), nullable=False)

    system_code: Mapped[str] = mapped_column(String(100), nullable=False)
    external_identifier: Mapped[str] = mapped_column(String(255), nullable=False)

    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    created_at: Mapped[datetime.datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime.datetime] = mapped_column(server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("system_code", "external_identifier", name="ux_provider_external_identifier"),
        Index("ix_provider_external_ids_provider", "provider_id"),
    )


class EventOutbox(Base):
    """Providers module's own transactional outbox (spec 2.2, 29). Same
    shape and rationale as Identity/Onboarding's `event_outbox` — see
    `app.modules.identity.domain.models.EventOutbox`'s docstring.
    """

    __tablename__ = "providers_event_outbox"

    id: Mapped[uuid.UUID] = uuid_pk()

    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    aggregate_type: Mapped[str] = mapped_column(String(100), nullable=False, default="Provider")
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
            name="providers_event_outbox_status_check",
        ),
        Index("ix_providers_event_outbox_pending", "created_at", postgresql_where=text("status = 'PENDING'")),
    )
