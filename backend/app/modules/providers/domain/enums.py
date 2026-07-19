"""Enum value sets for the Providers module (spec sections 3, 6, 11.5, 13.5,
15, 16.2, 17.2, 17.3, 30.11).

Plain `str, Enum` classes, same style as
`app.modules.identity.domain.enums`/`app.modules.onboarding.domain.enums`
— values are transcribed directly from the spec's CHECK constraints so the
Python-side and database-side vocabularies never drift apart.
"""

from __future__ import annotations

from enum import Enum


class ProviderType(str, Enum):
    """Spec section 3. DOCTOR/NUTRITIONIST are the only types reachable
    through Identity registration today; the rest are modelled so the
    schema and domain logic don't need to change when they're onboarded.
    """

    DOCTOR = "DOCTOR"
    NUTRITIONIST = "NUTRITIONIST"
    DENTIST = "DENTIST"
    PSYCHOLOGIST = "PSYCHOLOGIST"
    PHYSIOTHERAPIST = "PHYSIOTHERAPIST"
    NURSE = "NURSE"
    PHARMACIST = "PHARMACIST"
    LABORATORY_PROFESSIONAL = "LABORATORY_PROFESSIONAL"
    FITNESS_PROFESSIONAL = "FITNESS_PROFESSIONAL"
    OTHER_HEALTH_PROFESSIONAL = "OTHER_HEALTH_PROFESSIONAL"


class VerificationStatus(str, Enum):
    """Spec section 6.1 — professional approval / regulatory standing."""

    NOT_VERIFIED = "NOT_VERIFIED"
    PENDING = "PENDING"
    VERIFIED = "VERIFIED"
    CONDITIONALLY_VERIFIED = "CONDITIONALLY_VERIFIED"
    REJECTED = "REJECTED"
    SUSPENDED = "SUSPENDED"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class ProfileStatus(str, Enum):
    """Spec section 6.2 — whether the profile can operate on the platform."""

    DRAFT = "DRAFT"
    INCOMPLETE = "INCOMPLETE"
    INACTIVE = "INACTIVE"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    DEACTIVATED = "DEACTIVATED"
    ARCHIVED = "ARCHIVED"


class PublicationStatus(str, Enum):
    """Spec section 6.3 — whether the provider appears in public channels."""

    UNPUBLISHED = "UNPUBLISHED"
    PUBLISHED = "PUBLISHED"
    HIDDEN = "HIDDEN"
    REMOVED = "REMOVED"


class ServiceStatus(str, Enum):
    """Spec section 6.4."""

    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
    SUSPENDED = "SUSPENDED"
    ARCHIVED = "ARCHIVED"


class AffiliationStatus(str, Enum):
    """Spec section 6.5."""

    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    REJECTED = "REJECTED"
    SUSPENDED = "SUSPENDED"
    ENDED = "ENDED"
    CANCELLED = "CANCELLED"


class RegistrationStatus(str, Enum):
    """Spec section 30.2 `registration_status` check."""

    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
    EXPIRED = "EXPIRED"
    SUSPENDED = "SUSPENDED"
    REVOKED = "REVOKED"
    SUPERSEDED = "SUPERSEDED"


class CredentialVerificationStatus(str, Enum):
    """Shared by professional registrations and qualifications (spec
    30.2/30.3 `verification_status` checks — identical value sets).
    """

    UNVERIFIED = "UNVERIFIED"
    PENDING = "PENDING"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"
    UNVERIFIABLE = "UNVERIFIABLE"


class QualificationType(str, Enum):
    """Spec section 11.5."""

    UNDERGRADUATE_DEGREE = "UNDERGRADUATE_DEGREE"
    POSTGRADUATE_DEGREE = "POSTGRADUATE_DEGREE"
    DIPLOMA = "DIPLOMA"
    CERTIFICATE = "CERTIFICATE"
    BOARD_CERTIFICATION = "BOARD_CERTIFICATION"
    SPECIALIST_QUALIFICATION = "SPECIALIST_QUALIFICATION"
    PROFESSIONAL_COURSE = "PROFESSIONAL_COURSE"
    OTHER = "OTHER"


class SpecialityVerificationStatus(str, Enum):
    """Spec section 30.5 `provider_speciality_verification_check` — a
    narrower set than `CredentialVerificationStatus` (no UNVERIFIABLE).
    """

    UNVERIFIED = "UNVERIFIED"
    PENDING = "PENDING"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class LanguageProficiency(str, Enum):
    """Spec section 13.5."""

    BASIC = "BASIC"
    INTERMEDIATE = "INTERMEDIATE"
    FLUENT = "FLUENT"
    NATIVE = "NATIVE"


class DeliveryMode(str, Enum):
    """Spec section 15 / 30.8."""

    VIDEO = "VIDEO"
    AUDIO = "AUDIO"
    SECURE_CHAT = "SECURE_CHAT"
    IN_PERSON = "IN_PERSON"
    HOME_VISIT = "HOME_VISIT"
    GROUP_SESSION = "GROUP_SESSION"


# Modes that need real-time virtual-consultation capability rather than a
# physical location (spec section 15's rule list).
VIRTUAL_DELIVERY_MODES: frozenset[str] = frozenset(
    {DeliveryMode.VIDEO.value, DeliveryMode.AUDIO.value, DeliveryMode.SECURE_CHAT.value}
)


class LocationType(str, Enum):
    """Spec section 16.2."""

    PRIVATE_PRACTICE = "PRIVATE_PRACTICE"
    HOSPITAL = "HOSPITAL"
    CLINIC = "CLINIC"
    VIRTUAL = "VIRTUAL"
    HOME_VISIT_SERVICE_AREA = "HOME_VISIT_SERVICE_AREA"
    OTHER = "OTHER"


class AffiliationType(str, Enum):
    """Spec section 17.2."""

    EMPLOYED = "EMPLOYED"
    CONTRACTED = "CONTRACTED"
    VISITING = "VISITING"
    PRACTICE_PRIVILEGES = "PRACTICE_PRIVILEGES"
    VOLUNTEER = "VOLUNTEER"
    OWNER = "OWNER"
    DIRECTOR = "DIRECTOR"
    OTHER = "OTHER"


class AffiliationSource(str, Enum):
    """Spec section 17.3."""

    SELF_DECLARED = "SELF_DECLARED"
    INSTITUTION_REGISTERED = "INSTITUTION_REGISTERED"
    BACK_OFFICE_CREATED = "BACK_OFFICE_CREATED"
    ONBOARDING_VERIFIED = "ONBOARDING_VERIFIED"


class MediaType(str, Enum):
    """Spec section 30.11 `media_type` check."""

    PROFILE_PHOTO = "PROFILE_PHOTO"
    COVER_IMAGE = "COVER_IMAGE"
    INTRODUCTION_VIDEO = "INTRODUCTION_VIDEO"
    OTHER = "OTHER"


class MediaProcessingStatus(str, Enum):
    """Spec section 30.11 `processing_status` check — same vocabulary as
    `app.shared.documents.port.DocumentStatus`, kept as its own enum since
    this table's constraint additionally allows `DELETED`.
    """

    PENDING_UPLOAD = "PENDING_UPLOAD"
    UPLOADED = "UPLOADED"
    PROCESSING = "PROCESSING"
    AVAILABLE = "AVAILABLE"
    REJECTED = "REJECTED"
    DELETED = "DELETED"


class ModerationStatus(str, Enum):
    """Spec section 30.11 `moderation_status` check."""

    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    NOT_REQUIRED = "NOT_REQUIRED"


class StatusHistoryType(str, Enum):
    """Spec section 30.13 `status_type` check."""

    VERIFICATION_STATUS = "VERIFICATION_STATUS"
    PROFILE_STATUS = "PROFILE_STATUS"
    PUBLICATION_STATUS = "PUBLICATION_STATUS"


class PublicationAction(str, Enum):
    """Spec section 30.14 `action` check."""

    PUBLISHED = "PUBLISHED"
    UNPUBLISHED = "UNPUBLISHED"
    HIDDEN = "HIDDEN"
    RESTORED = "RESTORED"
    REMOVED = "REMOVED"


# Provider types that require at least one professional registration to be
# considered for verification (spec section 3's examples: "Doctors require
# a medical council registration. Nutritionists may require a nutrition or
# allied-health registration."). Both initial types require one; kept as a
# set (rather than hard-coding "all types") so a future type without a
# registration requirement (e.g. FITNESS_PROFESSIONAL) is a one-line change.
REGISTRATION_REQUIRED_TYPES: frozenset[str] = frozenset({ProviderType.DOCTOR.value, ProviderType.NUTRITIONIST.value})

# Provider types allowed to issue prescriptions, subject to VERIFIED status
# and an active primary registration (spec section 27's worked example).
PRESCRIBING_PROVIDER_TYPES: frozenset[str] = frozenset({ProviderType.DOCTOR.value})
