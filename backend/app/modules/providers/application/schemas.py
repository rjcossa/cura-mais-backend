"""Pydantic request/response DTOs for every Providers endpoint. All
subclass `CamelModel` (`app.core.schema_base`) for automatic camelCase
aliasing, same convention as Identity/Onboarding's `schemas.py`.
"""

from __future__ import annotations

import datetime
import uuid

from pydantic import Field

from app.core.schema_base import CamelModel

# --- Profile (spec 9) ---------------------------------------------------------


class ProviderProfileOut(CamelModel):
    id: uuid.UUID
    user_id: uuid.UUID
    provider_type: str
    first_name: str
    middle_name: str | None
    last_name: str
    professional_title: str | None
    display_name: str | None
    slug: str
    short_biography: str | None
    biography: str | None
    date_of_birth: datetime.date | None
    gender: str | None
    nationality: str | None
    years_of_experience: int | None
    verification_status: str
    profile_status: str
    publication_status: str
    profile_completion_percentage: int
    approval_reference: str | None
    approval_valid_until: datetime.datetime | None
    created_at: datetime.datetime
    updated_at: datetime.datetime
    version: int


class UpdateProviderProfileRequest(CamelModel):
    first_name: str | None = None
    middle_name: str | None = None
    last_name: str | None = None
    professional_title: str | None = None
    display_name: str | None = None
    short_biography: str | None = None
    biography: str | None = None
    date_of_birth: datetime.date | None = None
    gender: str | None = None
    nationality: str | None = None
    years_of_experience: int | None = None
    version: int


class CompletenessOut(CamelModel):
    complete: bool
    completion_percentage: int
    missing_fields: list[str]
    missing_relationships: list[str]
    missing_requirements: list[str]
    publication_eligible: bool


# --- Professional registrations (spec 10) ---------------------------------------


class RegistrationOut(CamelModel):
    id: uuid.UUID
    registration_type: str
    registration_number: str
    registration_authority: str
    registration_country: str
    issue_date: datetime.date | None
    expiry_date: datetime.date | None
    registration_status: str
    verification_status: str
    is_primary: bool
    decision_locked: bool
    created_at: datetime.datetime
    updated_at: datetime.datetime
    version: int


class CreateRegistrationRequest(CamelModel):
    registration_type: str
    registration_number: str = Field(min_length=1)
    registration_authority: str = Field(min_length=1)
    registration_country: str = Field(min_length=2, max_length=2)
    issue_date: datetime.date | None = None
    expiry_date: datetime.date | None = None
    is_primary: bool = False


class UpdateRegistrationRequest(CamelModel):
    registration_type: str | None = None
    registration_number: str | None = None
    registration_authority: str | None = None
    registration_country: str | None = None
    issue_date: datetime.date | None = None
    expiry_date: datetime.date | None = None


# --- Qualifications (spec 11) -----------------------------------------------------


class QualificationOut(CamelModel):
    id: uuid.UUID
    qualification_type: str
    qualification_name: str
    institution_name: str
    institution_country: str | None
    start_date: datetime.date | None
    completion_date: datetime.date | None
    speciality_id: uuid.UUID | None
    verification_status: str
    decision_locked: bool
    created_at: datetime.datetime
    updated_at: datetime.datetime
    version: int


class CreateQualificationRequest(CamelModel):
    qualification_type: str
    qualification_name: str = Field(min_length=1)
    institution_name: str = Field(min_length=1)
    institution_country: str | None = None
    start_date: datetime.date | None = None
    completion_date: datetime.date | None = None
    speciality_id: uuid.UUID | None = None


class UpdateQualificationRequest(CamelModel):
    qualification_type: str | None = None
    qualification_name: str | None = None
    institution_name: str | None = None
    institution_country: str | None = None
    start_date: datetime.date | None = None
    completion_date: datetime.date | None = None
    speciality_id: uuid.UUID | None = None


# --- Specialities (spec 12) -------------------------------------------------------


class SpecialityReferenceOut(CamelModel):
    id: uuid.UUID
    code: str
    name: str
    description: str | None
    provider_type: str
    parent_speciality_id: uuid.UUID | None
    requires_verified_qualification: bool
    active: bool


class ProviderSpecialityOut(CamelModel):
    id: uuid.UUID
    speciality_id: uuid.UUID
    is_primary: bool
    years_of_experience: int | None
    verification_status: str
    created_at: datetime.datetime
    updated_at: datetime.datetime
    version: int


class AddSpecialityRequest(CamelModel):
    speciality_id: uuid.UUID
    is_primary: bool = False
    years_of_experience: int | None = None


class UpdateSpecialityRequest(CamelModel):
    years_of_experience: int | None = None


# --- Languages (spec 13) -----------------------------------------------------------


class LanguageOut(CamelModel):
    language_code: str
    proficiency: str
    can_consult: bool
    created_at: datetime.datetime
    updated_at: datetime.datetime


class AddLanguageRequest(CamelModel):
    language_code: str
    proficiency: str
    can_consult: bool = True


class UpdateLanguageRequest(CamelModel):
    proficiency: str | None = None
    can_consult: bool | None = None


# --- Services (spec 14) -------------------------------------------------------------


class ServiceOut(CamelModel):
    id: uuid.UUID
    service_code: str
    name: str
    description: str | None
    speciality_id: uuid.UUID | None
    duration_minutes: int
    price: float | None
    currency: str | None
    pro_bono: bool
    requires_pre_screening: bool
    minimum_patient_age: int | None
    maximum_patient_age: int | None
    # No default source attribute on the ORM object (delivery modes live in
    # a separate join table, `provider_service_modes`) — defaults to empty
    # so `ServiceOut.model_validate(service, from_attributes=True)`
    # succeeds before the route overwrites this with the real list fetched
    # separately (see api/services_routes.py's `_out` / `backoffice_routes.py`'s
    # service serialization).
    delivery_modes: list[str] = Field(default_factory=list)
    booking_notice_minutes: int
    cancellation_notice_minutes: int
    status: str
    publicly_visible: bool
    created_at: datetime.datetime
    updated_at: datetime.datetime
    version: int


class CreateServiceRequest(CamelModel):
    service_code: str = Field(min_length=1)
    name: str = Field(min_length=1)
    description: str | None = None
    speciality_id: uuid.UUID | None = None
    duration_minutes: int = Field(ge=5, le=480)
    price: float | None = None
    currency: str | None = None
    pro_bono: bool = False
    requires_pre_screening: bool = False
    minimum_patient_age: int | None = None
    maximum_patient_age: int | None = None
    delivery_modes: list[str] = Field(default_factory=list)
    booking_notice_minutes: int = 0
    cancellation_notice_minutes: int = 0
    status: str = "DRAFT"


class UpdateServiceRequest(CamelModel):
    name: str | None = None
    description: str | None = None
    speciality_id: uuid.UUID | None = None
    duration_minutes: int | None = None
    price: float | None = None
    currency: str | None = None
    pro_bono: bool | None = None
    requires_pre_screening: bool | None = None
    minimum_patient_age: int | None = None
    maximum_patient_age: int | None = None
    delivery_modes: list[str] | None = None
    booking_notice_minutes: int | None = None
    cancellation_notice_minutes: int | None = None
    publicly_visible: bool | None = None


# --- Locations (spec 16) ------------------------------------------------------------


class LocationOut(CamelModel):
    id: uuid.UUID
    institution_id: uuid.UUID | None
    department_id: uuid.UUID | None
    location_type: str
    name: str
    address_line_1: str | None
    address_line_2: str | None
    city: str | None
    province: str | None
    postal_code: str | None
    country_code: str | None
    latitude: float | None
    longitude: float | None
    contact_number: str | None
    wheelchair_accessible: bool | None
    parking_available: bool | None
    is_primary: bool
    active: bool
    created_at: datetime.datetime
    updated_at: datetime.datetime
    version: int


class CreateLocationRequest(CamelModel):
    location_type: str
    name: str = Field(min_length=1)
    address_line_1: str | None = None
    address_line_2: str | None = None
    city: str | None = None
    province: str | None = None
    postal_code: str | None = None
    country_code: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    contact_number: str | None = None
    wheelchair_accessible: bool | None = None
    parking_available: bool | None = None
    is_primary: bool = False


class UpdateLocationRequest(CamelModel):
    name: str | None = None
    address_line_1: str | None = None
    address_line_2: str | None = None
    city: str | None = None
    province: str | None = None
    postal_code: str | None = None
    country_code: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    contact_number: str | None = None
    wheelchair_accessible: bool | None = None
    parking_available: bool | None = None


# --- Affiliations (spec 17) ---------------------------------------------------------


class AffiliationOut(CamelModel):
    id: uuid.UUID
    institution_id: uuid.UUID
    department_id: uuid.UUID | None
    affiliation_type: str
    affiliation_source: str
    professional_position: str | None
    start_date: datetime.date | None
    end_date: datetime.date | None
    status: str
    confirmed_at: datetime.datetime | None
    rejection_reason: str | None
    ended_reason: str | None
    created_at: datetime.datetime
    updated_at: datetime.datetime
    version: int


class CreateAffiliationRequest(CamelModel):
    institution_id: uuid.UUID
    department_id: uuid.UUID | None = None
    affiliation_type: str
    professional_position: str | None = None
    start_date: datetime.date | None = None
    end_date: datetime.date | None = None


class UpdateAffiliationRequest(CamelModel):
    professional_position: str | None = None
    start_date: datetime.date | None = None
    end_date: datetime.date | None = None


class EndAffiliationRequest(CamelModel):
    end_date: datetime.date
    reason: str | None = None


class RejectAffiliationRequest(CamelModel):
    reason: str = Field(min_length=1)


# --- Media (spec 18) -----------------------------------------------------------------


class CreateMediaUploadRequest(CamelModel):
    file_name: str = Field(min_length=1)
    mime_type: str
    file_size: int = Field(gt=0)


class MediaUploadRequestOut(CamelModel):
    media_id: uuid.UUID
    document_id: uuid.UUID
    upload_url: str
    expires_at: datetime.datetime


class ConfirmMediaUploadRequest(CamelModel):
    checksum: str = Field(min_length=1)


class MediaOut(CamelModel):
    id: uuid.UUID
    media_type: str
    processing_status: str
    moderation_status: str
    active: bool


# --- Publication (spec 19) ------------------------------------------------------------


class PublishProviderRequest(CamelModel):
    confirm_public_profile: bool = True


class HideProviderRequest(CamelModel):
    reason_code: str = Field(min_length=1)
    comments: str | None = None


# --- Public provider view (spec 20) ---------------------------------------------------


class PublicSpecialityOut(CamelModel):
    id: uuid.UUID
    code: str
    name: str


class PublicLanguageOut(CamelModel):
    code: str
    name: str | None = None


class PublicServiceOut(CamelModel):
    id: uuid.UUID
    name: str
    duration_minutes: int
    price: float | None
    currency: str | None
    pro_bono: bool
    delivery_modes: list[str]


class PublicLocationOut(CamelModel):
    id: uuid.UUID
    name: str
    city: str | None
    province: str | None
    country_code: str | None


class PublicAffiliationOut(CamelModel):
    institution_id: uuid.UUID
    professional_position: str | None


class PublicProviderOut(CamelModel):
    id: uuid.UUID
    provider_type: str
    display_name: str | None
    slug: str
    professional_title: str | None
    short_biography: str | None
    biography: str | None
    years_of_experience: int | None
    verification_badge: str
    primary_speciality: PublicSpecialityOut | None
    specialities: list[PublicSpecialityOut]
    languages: list[PublicLanguageOut]
    services: list[PublicServiceOut]
    locations: list[PublicLocationOut]
    affiliations: list[PublicAffiliationOut]


# --- Back office (spec 22) --------------------------------------------------------------


class ProviderSearchResultOut(CamelModel):
    id: uuid.UUID
    provider_type: str
    display_name: str | None
    slug: str
    verification_status: str
    profile_status: str
    publication_status: str
    profile_completion_percentage: int
    created_at: datetime.datetime


class PagedProvidersOut(CamelModel):
    content: list[ProviderSearchResultOut]
    page: int
    size: int
    total_elements: int
    total_pages: int


class CorrectProviderRequest(CamelModel):
    updates: dict = Field(default_factory=dict)
    reason: str = Field(min_length=1)
    version: int


class SuspendProviderRequest(CamelModel):
    reason_code: str = Field(min_length=1)
    comments: str | None = None
    source_reference: str | None = None


class ReinstateProviderRequest(CamelModel):
    approval_reference: str | None = None
    comments: str | None = None


class StatusHistoryOut(CamelModel):
    id: uuid.UUID
    status_type: str
    previous_status: str | None
    new_status: str
    reason_code: str | None
    comments: str | None
    source_type: str | None
    source_reference: str | None
    changed_by: uuid.UUID | None
    created_at: datetime.datetime


class PublicationHistoryOut(CamelModel):
    id: uuid.UUID
    action: str
    reason_code: str | None
    comments: str | None
    performed_by: uuid.UUID | None
    created_at: datetime.datetime
