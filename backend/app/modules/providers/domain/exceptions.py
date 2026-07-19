"""Providers module error codes (spec section 33) mapped to HTTP status
codes, following the exact same pattern as
`app.modules.onboarding.domain.exceptions.OnboardingError`.

A handful of codes beyond spec section 33 are added for aggregates the
spec gives endpoints for but no dedicated error-code list (languages,
media) — named the same `PROVIDER_<RESOURCE>_<PROBLEM>` way as the
spec's own codes, same discretion `OnboardingError` already exercises for
e.g. `ONBOARDING_PARTY_NOT_FOUND`.
"""

from __future__ import annotations

from app.core.exceptions import AppError, ErrorField

_REGISTRY: dict[str, tuple[int, str]] = {
    # 33.1 Provider profile
    "PROVIDER_NOT_FOUND": (404, "The provider was not found."),
    "PROVIDER_ALREADY_EXISTS": (409, "A provider already exists for this user and provider type."),
    "PROVIDER_TYPE_INVALID": (422, "This provider type is not supported."),
    "PROVIDER_PROFILE_NOT_EDITABLE": (409, "The provider profile can no longer be edited."),
    "PROVIDER_PROFILE_INCOMPLETE": (422, "The provider profile cannot be published because mandatory requirements are outstanding."),
    "PROVIDER_PROFILE_VERSION_CONFLICT": (409, "The provider profile was modified elsewhere. Please refresh and try again."),
    "PROVIDER_NOT_ACTIVE": (409, "The provider profile is not active."),
    "PROVIDER_NOT_VERIFIED": (409, "The provider is not verified."),
    "PROVIDER_SUSPENDED": (409, "The provider is suspended."),
    "PROVIDER_PUBLICATION_NOT_ALLOWED": (409, "The provider does not meet the preconditions for publication."),
    "PROVIDER_ALREADY_PUBLISHED": (409, "The provider profile is already published."),
    "PROVIDER_NOT_PUBLISHED": (409, "The provider profile is not published."),
    # 33.2 Registration
    "PROVIDER_REGISTRATION_NOT_FOUND": (404, "The professional registration was not found."),
    "PROVIDER_REGISTRATION_ALREADY_EXISTS": (409, "A registration with this number, authority, and country already exists."),
    "PROVIDER_REGISTRATION_INVALID": (422, "The professional registration is invalid."),
    "PROVIDER_REGISTRATION_EXPIRED": (422, "The professional registration has expired."),
    "PROVIDER_REGISTRATION_LOCKED": (409, "This registration is locked by a completed decision and cannot be changed."),
    "PROVIDER_PRIMARY_REGISTRATION_REQUIRED": (422, "At least one primary professional registration is required."),
    "PROVIDER_REGISTRATION_REVERIFICATION_REQUIRED": (409, "This change to a verified registration requires re-verification."),
    # 33.3 Qualification
    "PROVIDER_QUALIFICATION_NOT_FOUND": (404, "The qualification was not found."),
    "PROVIDER_QUALIFICATION_INVALID": (422, "The qualification is invalid."),
    "PROVIDER_QUALIFICATION_LOCKED": (409, "This qualification is locked by a completed decision and cannot be changed."),
    "PROVIDER_QUALIFICATION_REQUIRED": (422, "At least one qualification is required."),
    # 33.4 Speciality
    "PROVIDER_SPECIALITY_NOT_FOUND": (404, "The speciality was not found."),
    "PROVIDER_SPECIALITY_NOT_ALLOWED": (422, "This speciality is not available for this provider type."),
    "PROVIDER_SPECIALITY_ALREADY_ASSIGNED": (409, "This speciality is already assigned to the provider."),
    "PROVIDER_PRIMARY_SPECIALITY_REQUIRED": (422, "At least one primary speciality is required."),
    "PROVIDER_SPECIALITY_QUALIFICATION_REQUIRED": (422, "This speciality requires a verified supporting qualification."),
    # 33.5 Service
    "PROVIDER_SERVICE_NOT_FOUND": (404, "The service was not found."),
    "PROVIDER_SERVICE_ALREADY_EXISTS": (409, "A service with this code already exists."),
    "PROVIDER_SERVICE_INVALID": (422, "The service is invalid."),
    "PROVIDER_SERVICE_ACTIVATION_NOT_ALLOWED": (409, "The service does not meet the preconditions for activation."),
    "PROVIDER_SERVICE_DELIVERY_MODE_REQUIRED": (422, "At least one delivery mode is required."),
    "PROVIDER_SERVICE_LOCATION_REQUIRED": (422, "An active physical location is required for this delivery mode."),
    "PROVIDER_SERVICE_PRICE_INVALID": (422, "The service price is invalid."),
    "PROVIDER_SERVICE_ALREADY_ACTIVE": (409, "The service is already active."),
    "PROVIDER_SERVICE_ALREADY_ARCHIVED": (409, "The service is already archived."),
    # 33.6 Location
    "PROVIDER_LOCATION_NOT_FOUND": (404, "The location was not found."),
    "PROVIDER_LOCATION_INVALID": (422, "The location is invalid."),
    "PROVIDER_LOCATION_IN_USE": (409, "This location is used by an active service and cannot be deactivated directly."),
    "PROVIDER_PRIMARY_LOCATION_REQUIRED": (422, "At least one primary location is required."),
    "PROVIDER_INSTITUTION_LOCATION_NOT_EDITABLE": (403, "Institution-owned location details cannot be edited directly."),
    # 33.7 Affiliation
    "PROVIDER_AFFILIATION_NOT_FOUND": (404, "The affiliation was not found."),
    "PROVIDER_AFFILIATION_ALREADY_EXISTS": (409, "An active affiliation with this institution, department, and type already exists."),
    "PROVIDER_AFFILIATION_STATE_INVALID": (409, "The affiliation is not in a state that allows this action."),
    "PROVIDER_AFFILIATION_INSTITUTION_INVALID": (422, "The institution does not exist or is not active."),
    "PROVIDER_AFFILIATION_CONFIRMATION_REQUIRED": (409, "This affiliation has not yet been confirmed."),
    # Language / media — not given dedicated codes in spec section 33, named
    # to match its convention.
    "PROVIDER_LANGUAGE_NOT_FOUND": (404, "The consultation language was not found."),
    "PROVIDER_LANGUAGE_ALREADY_EXISTS": (409, "This language is already recorded for the provider."),
    "PROVIDER_LANGUAGE_INVALID": (422, "The language code or proficiency is invalid."),
    "PROVIDER_MEDIA_NOT_FOUND": (404, "The media item was not found."),
    "PROVIDER_MEDIA_INVALID": (422, "The file type or size is not accepted for this media type."),
}


class ProviderError(AppError):
    @classmethod
    def for_code(
        cls,
        code: str,
        message: str | None = None,
        *,
        fields: list[ErrorField] | None = None,
        details: dict | None = None,
    ) -> ProviderError:
        status_code, default_message = _REGISTRY.get(code, (400, "The request could not be completed."))
        return cls(
            code=code, message=message or default_message, status_code=status_code, fields=fields, details=details
        )
