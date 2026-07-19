"""Domain events published by the Providers module (spec section 29).

Same transactional-outbox pattern as Identity/Onboarding: written to this
module's own `providers_event_outbox` table in the same transaction as the
business change, delivered by `app.core.outbox.OutboxDispatcher` outside
any request transaction. See `application/outbox_dispatcher.py`.
"""

from __future__ import annotations


class ProviderEvent:
    CREATED = "ProviderCreated"
    PROFILE_UPDATED = "ProviderProfileUpdated"
    MATERIAL_CHANGE_DETECTED = "ProviderMaterialChangeDetected"
    PROFILE_COMPLETED = "ProviderProfileCompleted"

    REGISTRATION_ADDED = "ProviderRegistrationAdded"
    REGISTRATION_UPDATED = "ProviderRegistrationUpdated"
    REGISTRATION_EXPIRING = "ProviderRegistrationExpiring"
    REGISTRATION_EXPIRED = "ProviderRegistrationExpired"

    QUALIFICATION_ADDED = "ProviderQualificationAdded"
    QUALIFICATION_VERIFIED = "ProviderQualificationVerified"

    SPECIALITY_ADDED = "ProviderSpecialityAdded"
    SPECIALITY_REMOVED = "ProviderSpecialityRemoved"
    PRIMARY_SPECIALITY_CHANGED = "ProviderPrimarySpecialityChanged"

    LANGUAGE_ADDED = "ProviderLanguageAdded"
    LANGUAGE_REMOVED = "ProviderLanguageRemoved"

    SERVICE_CREATED = "ProviderServiceCreated"
    SERVICE_ACTIVATED = "ProviderServiceActivated"
    SERVICE_DEACTIVATED = "ProviderServiceDeactivated"
    SERVICE_ARCHIVED = "ProviderServiceArchived"

    LOCATION_ADDED = "ProviderLocationAdded"
    LOCATION_UPDATED = "ProviderLocationUpdated"
    LOCATION_DEACTIVATED = "ProviderLocationDeactivated"

    AFFILIATION_REQUESTED = "ProviderAffiliationRequested"
    AFFILIATION_CONFIRMED = "ProviderAffiliationConfirmed"
    AFFILIATION_REJECTED = "ProviderAffiliationRejected"
    AFFILIATION_ENDED = "ProviderAffiliationEnded"

    PUBLICATION_REQUESTED = "ProviderPublicationRequested"
    PUBLISHED = "ProviderPublished"
    UNPUBLISHED = "ProviderUnpublished"
    HIDDEN = "ProviderHidden"

    ACTIVATED = "ProviderActivated"
    CONDITIONALLY_ACTIVATED = "ProviderConditionallyActivated"
    SUSPENDED = "ProviderSuspended"
    REINSTATED = "ProviderReinstated"
    ARCHIVED = "ProviderArchived"


class ProviderNotification:
    """Template codes requested from the (future) Notification module
    (spec section 28) — dispatched to the mocked adapters in
    `app/core/notifications.py`, same as Identity/Onboarding do today.
    """

    PROFILE_CREATED = "PROVIDER_PROFILE_CREATED"
    PROFILE_COMPLETION_REMINDER = "PROVIDER_PROFILE_COMPLETION_REMINDER"
    PROFILE_PUBLISHED = "PROVIDER_PROFILE_PUBLISHED"
    PROFILE_UNPUBLISHED = "PROVIDER_PROFILE_UNPUBLISHED"
    SERVICE_ACTIVATED = "PROVIDER_SERVICE_ACTIVATED"
    SERVICE_SUSPENDED = "PROVIDER_SERVICE_SUSPENDED"
    AFFILIATION_REQUESTED = "PROVIDER_AFFILIATION_REQUESTED"
    AFFILIATION_CONFIRMED = "PROVIDER_AFFILIATION_CONFIRMED"
    AFFILIATION_REJECTED = "PROVIDER_AFFILIATION_REJECTED"
    REGISTRATION_EXPIRING = "PROVIDER_REGISTRATION_EXPIRING"
    REGISTRATION_EXPIRED = "PROVIDER_REGISTRATION_EXPIRED"
    SUSPENDED = "PROVIDER_SUSPENDED"
    REINSTATED = "PROVIDER_REINSTATED"
    MATERIAL_CHANGE_REVERIFICATION_REQUIRED = "PROVIDER_MATERIAL_CHANGE_REVERIFICATION_REQUIRED"
