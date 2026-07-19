"""Publication workflow and eligibility validation (spec sections 19,
33.1, 37.10). This is also `ProviderValidationService.validateForPublication`
(spec 31.3) — `check_eligibility` is reused by both the API's
`GET /me/completeness` (`publicationEligible` flag) and the actual
`publish()` transaction, so the two can never disagree about what's
required.
"""

from __future__ import annotations

import datetime
import uuid

from app.modules.providers.application.completeness_service import CompletenessService
from app.modules.providers.domain.events import ProviderEvent
from app.modules.providers.domain.exceptions import ProviderError
from app.modules.providers.domain.models import Provider, ProviderPublicationHistory, ProviderStatusHistory
from app.modules.providers.domain.repositories import (
    LanguageRepository,
    OutboxRepository,
    ProviderRepository,
    QualificationRepository,
    RegistrationRepository,
    ServiceRepository,
    SpecialityRepository,
)
from app.modules.providers.infrastructure.identity_adapter import IdentityPort

_ELIGIBLE_VERIFICATION_STATUSES = {"VERIFIED", "CONDITIONALLY_VERIFIED"}


class PublicationService:
    def __init__(
        self,
        provider_repo: ProviderRepository,
        registration_repo: RegistrationRepository,
        qualification_repo: QualificationRepository,
        speciality_repo: SpecialityRepository,
        language_repo: LanguageRepository,
        service_repo: ServiceRepository,
        completeness_service: CompletenessService,
        identity: IdentityPort,
        outbox_repo: OutboxRepository,
    ) -> None:
        self._providers = provider_repo
        self._registrations = registration_repo
        self._qualifications = qualification_repo
        self._specialities = speciality_repo
        self._languages = language_repo
        self._services = service_repo
        self._completeness = completeness_service
        self._identity = identity
        self._outbox = outbox_repo

    async def check_eligibility(self, provider: Provider) -> None:
        """Raises a `ProviderError` on the first unmet precondition
        (spec 19.2); returns normally when the provider may be published.
        """
        if not await self._identity.is_user_active(provider.user_id):
            raise ProviderError.for_code("PROVIDER_NOT_ACTIVE", "The provider's Identity account is not active.")
        if not await self._identity.has_role(provider.user_id, provider.provider_type):
            raise ProviderError.for_code("PROVIDER_NOT_VERIFIED", "The provider does not hold the approved provider role.")
        if provider.verification_status not in _ELIGIBLE_VERIFICATION_STATUSES:
            raise ProviderError.for_code("PROVIDER_NOT_VERIFIED")
        if provider.profile_status != "ACTIVE":
            raise ProviderError.for_code("PROVIDER_NOT_ACTIVE")

        completeness = await self._completeness.calculate(provider)
        if not completeness.complete or completeness.missing_requirements:
            raise ProviderError.for_code(
                "PROVIDER_PROFILE_INCOMPLETE",
                details={
                    "missingFields": completeness.missing_fields,
                    "missingRequirements": completeness.missing_relationships + completeness.missing_requirements,
                },
            )

        primary_speciality = await self._specialities.get_primary(provider.id)
        if primary_speciality is None:
            raise ProviderError.for_code("PROVIDER_PRIMARY_SPECIALITY_REQUIRED")

        speciality = await self._specialities.get_reference_by_id(primary_speciality.speciality_id)
        if speciality is not None and speciality.requires_verified_qualification:
            qualifications = await self._qualifications.list_for_provider(provider.id)
            has_supporting = any(
                q.speciality_id == primary_speciality.speciality_id and q.verification_status == "VERIFIED"
                for q in qualifications
            )
            if not has_supporting:
                raise ProviderError.for_code("PROVIDER_SPECIALITY_QUALIFICATION_REQUIRED")

        primary_registration = await self._registrations.get_active_primary(provider.id)
        if primary_registration is None:
            raise ProviderError.for_code("PROVIDER_PRIMARY_REGISTRATION_REQUIRED")

    async def publish(self, provider: Provider, *, performed_by: uuid.UUID | None) -> Provider:
        if provider.publication_status == "PUBLISHED":
            raise ProviderError.for_code("PROVIDER_ALREADY_PUBLISHED")

        await self._outbox.enqueue(
            ProviderEvent.PUBLICATION_REQUESTED, {"providerId": str(provider.id)}, aggregate_id=provider.id
        )
        await self.check_eligibility(provider)

        previous = provider.publication_status
        provider.publication_status = "PUBLISHED"
        provider.published_at = datetime.datetime.now(datetime.UTC)

        await self._write_history(provider, previous, "PUBLISHED")
        await self._record_publication_history(provider, "PUBLISHED", performed_by=performed_by)

        await self._outbox.enqueue(
            ProviderEvent.PUBLISHED,
            {"providerId": str(provider.id), "slug": provider.slug},
            aggregate_id=provider.id,
        )
        return provider

    async def unpublish(self, provider: Provider, *, performed_by: uuid.UUID | None) -> Provider:
        if provider.publication_status != "PUBLISHED":
            raise ProviderError.for_code("PROVIDER_NOT_PUBLISHED")

        provider.publication_status = "UNPUBLISHED"
        await self._write_history(provider, "PUBLISHED", "UNPUBLISHED")
        await self._record_publication_history(provider, "UNPUBLISHED", performed_by=performed_by)

        await self._outbox.enqueue(ProviderEvent.UNPUBLISHED, {"providerId": str(provider.id)}, aggregate_id=provider.id)
        return provider

    async def _write_history(self, provider: Provider, previous: str, new: str) -> None:
        await self._providers.add_status_history(
            ProviderStatusHistory(
                provider_id=provider.id, status_type="PUBLICATION_STATUS", previous_status=previous, new_status=new
            )
        )

    async def _record_publication_history(self, provider: Provider, action: str, *, performed_by: uuid.UUID | None) -> None:
        await self._providers.add_publication_history(
            ProviderPublicationHistory(provider_id=provider.id, action=action, performed_by=performed_by)
        )
