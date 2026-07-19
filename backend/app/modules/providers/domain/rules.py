"""Pure business rules — no repository/session/clock dependencies, so
these are trivially unit-testable without a database (spec section 37's
requirement that unit tests isolate domain logic from Postgres etc.).
Application services fetch data through repositories, then hand plain
values to these functions.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.modules.providers.domain.enums import PRESCRIBING_PROVIDER_TYPES

# --- Material change detection (spec section 9.2) ----------------------------

# Only the Provider-table-level material fields live here. Registration
# number/authority and primary-speciality changes are detected by their
# own services (professional_registration_service.py,
# speciality_service.py) since they're separate aggregates — this set is
# deliberately narrower than spec 9.2's full material-fields list.
PROFILE_MATERIAL_FIELDS: frozenset[str] = frozenset(
    {"first_name", "last_name", "professional_title", "nationality", "provider_type"}
)


def detect_material_change(changed_fields: set[str]) -> bool:
    return bool(changed_fields & PROFILE_MATERIAL_FIELDS)


# --- Profile completeness / provider-type requirements (spec section 9.4) ----
#
# "Provider-specific rules should be configurable where practical" (spec
# section 3) — mirrors the configurability
# `app.modules.onboarding.application.section_definitions.REQUIRED_SECTIONS`
# already gives per applicant type, one config entry per provider type
# rather than hard-coded branches.


@dataclass(frozen=True, slots=True)
class ProviderTypeRequirements:
    required_credential: str  # "REGISTRATION" | "QUALIFICATION" — spec 9.4's asymmetry between the two initial types
    requires_primary_speciality: bool  # DOCTOR needs a *primary* speciality; NUTRITIONIST just needs one


PROVIDER_TYPE_REQUIREMENTS: dict[str, ProviderTypeRequirements] = {
    "DOCTOR": ProviderTypeRequirements(required_credential="REGISTRATION", requires_primary_speciality=True),
    "NUTRITIONIST": ProviderTypeRequirements(required_credential="QUALIFICATION", requires_primary_speciality=False),
}

# Provider types with no explicit entry (future types per spec section 3)
# fall back to the stricter DOCTOR-style profile (registration + primary
# speciality) rather than silently requiring nothing.
_DEFAULT_TYPE_REQUIREMENTS = PROVIDER_TYPE_REQUIREMENTS["DOCTOR"]


def requirements_for_type(provider_type: str) -> ProviderTypeRequirements:
    return PROVIDER_TYPE_REQUIREMENTS.get(provider_type, _DEFAULT_TYPE_REQUIREMENTS)


@dataclass(slots=True)
class CompletenessInputs:
    first_name: str | None
    last_name: str | None
    professional_title: str | None
    biography: str | None
    years_of_experience: int | None
    has_registration: bool
    has_qualification: bool
    has_primary_speciality: bool
    has_any_speciality: bool
    has_consult_language: bool
    has_profile_photo: bool
    has_active_service: bool


@dataclass(slots=True)
class CompletenessResult:
    complete: bool
    completion_percentage: int
    missing_fields: list[str] = field(default_factory=list)
    missing_relationships: list[str] = field(default_factory=list)
    missing_requirements: list[str] = field(default_factory=list)
    publication_eligible: bool = False


def compute_completeness(provider_type: str, inputs: CompletenessInputs) -> CompletenessResult:
    requirements = requirements_for_type(provider_type)

    missing_fields: list[str] = []
    if not inputs.first_name:
        missing_fields.append("firstName")
    if not inputs.last_name:
        missing_fields.append("lastName")
    if not inputs.professional_title:
        missing_fields.append("professionalTitle")
    if not inputs.biography:
        missing_fields.append("biography")
    if inputs.years_of_experience is None:
        missing_fields.append("yearsOfExperience")
    if not inputs.has_profile_photo:
        missing_fields.append("profilePhoto")

    missing_relationships: list[str] = []
    if requirements.required_credential == "REGISTRATION" and not inputs.has_registration:
        missing_relationships.append("PROFESSIONAL_REGISTRATION")
    if requirements.required_credential == "QUALIFICATION" and not inputs.has_qualification:
        missing_relationships.append("QUALIFICATION")
    if requirements.requires_primary_speciality:
        if not inputs.has_primary_speciality:
            missing_relationships.append("PRIMARY_SPECIALITY")
    elif not inputs.has_any_speciality:
        missing_relationships.append("SPECIALITY")
    if not inputs.has_consult_language:
        missing_relationships.append("CONSULTATION_LANGUAGE")

    # "At least one active service before publication" (spec 9.4) — tracked
    # as a *requirement* (blocks publication) rather than a *field*, since a
    # brand-new DRAFT provider isn't "incomplete" for lacking one yet.
    missing_requirements: list[str] = []
    if not inputs.has_active_service:
        missing_requirements.append("ACTIVE_SERVICE")

    total_checks = 6 + 3 + 1  # fields + relationships + active-service
    satisfied = total_checks - len(missing_fields) - len(missing_relationships) - len(missing_requirements)
    completion_percentage = max(0, min(100, round(100 * satisfied / total_checks)))

    complete = not missing_fields and not missing_relationships
    publication_eligible = complete and not missing_requirements

    return CompletenessResult(
        complete=complete,
        completion_percentage=completion_percentage,
        missing_fields=missing_fields,
        missing_relationships=missing_relationships,
        missing_requirements=missing_requirements,
        publication_eligible=publication_eligible,
    )


# --- Status-combination reference (spec section 7) ---------------------------
#
# The three status columns don't form one shared finite-state graph the way
# Onboarding's single `status` column does — each dimension moves somewhat
# independently — so rather than a generic `is_transition_allowed(from, to)`
# table, this documents the *resulting* combination for each named action
# (spec 7.1/7.4/7.5), applied by `application/profile_service.py`. Approval
# (7.3) and publication aren't here since they depend on runtime eligibility,
# not a fixed combination.

STATUS_ON_CREATE = ("NOT_VERIFIED", "DRAFT", "UNPUBLISHED")
STATUS_ON_SUBMIT_INCOMPLETE = ("PENDING", "INCOMPLETE", "UNPUBLISHED")
STATUS_ON_SUBMIT_COMPLETE = ("PENDING", "INACTIVE", "UNPUBLISHED")
STATUS_ON_SUSPEND = ("SUSPENDED", "SUSPENDED", "HIDDEN")
STATUS_ON_EXPIRE = ("EXPIRED", "INACTIVE", "HIDDEN")


# --- Prescription authority (spec section 27) ---------------------------------


def can_issue_prescription(provider_type: str, verification_status: str, has_active_primary_registration: bool) -> bool:
    return (
        provider_type in PRESCRIBING_PROVIDER_TYPES
        and verification_status == "VERIFIED"
        and has_active_primary_registration
    )
