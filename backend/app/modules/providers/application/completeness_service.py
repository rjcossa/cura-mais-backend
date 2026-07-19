"""Profile completeness calculation (spec sections 9.3, 9.4, 34.2's
"Recalculate profile completeness" step used by every mutating service).
"""

from __future__ import annotations

from app.modules.providers.domain.events import ProviderEvent
from app.modules.providers.domain.models import Provider
from app.modules.providers.domain.repositories import (
    LanguageRepository,
    MediaRepository,
    OutboxRepository,
    QualificationRepository,
    RegistrationRepository,
    ServiceRepository,
    SpecialityRepository,
)
from app.modules.providers.domain.rules import CompletenessInputs, CompletenessResult, compute_completeness


class CompletenessService:
    def __init__(
        self,
        registration_repo: RegistrationRepository,
        qualification_repo: QualificationRepository,
        speciality_repo: SpecialityRepository,
        language_repo: LanguageRepository,
        service_repo: ServiceRepository,
        media_repo: MediaRepository,
        outbox_repo: OutboxRepository,
    ) -> None:
        self._registrations = registration_repo
        self._qualifications = qualification_repo
        self._specialities = speciality_repo
        self._languages = language_repo
        self._services = service_repo
        self._media = media_repo
        self._outbox = outbox_repo

    async def calculate(self, provider: Provider) -> CompletenessResult:
        registrations = await self._registrations.list_for_provider(provider.id)
        qualifications = await self._qualifications.list_for_provider(provider.id)
        specialities = await self._specialities.list_for_provider(provider.id)
        languages = await self._languages.list_for_provider(provider.id)
        services = await self._services.list_for_provider(provider.id, status="ACTIVE")
        profile_photo = await self._media.get_active(provider.id, "PROFILE_PHOTO")

        inputs = CompletenessInputs(
            first_name=provider.first_name,
            last_name=provider.last_name,
            professional_title=provider.professional_title,
            biography=provider.biography,
            years_of_experience=provider.years_of_experience,
            has_registration=any(r.registration_status == "ACTIVE" for r in registrations),
            has_qualification=len(qualifications) > 0,
            has_primary_speciality=any(s.is_primary for s in specialities),
            has_any_speciality=len(specialities) > 0,
            has_consult_language=any(lang.can_consult for lang in languages),
            has_profile_photo=profile_photo is not None,
            has_active_service=len(services) > 0,
        )
        return compute_completeness(provider.provider_type, inputs)

    async def refresh(self, provider: Provider) -> CompletenessResult:
        """Recalculates and persists `profile_completion_percentage` on the
        given (already-loaded, not-yet-flushed) provider, publishing
        `ProviderProfileCompleted` only on the 0% -> 100%-complete
        transition (spec 37.2's "generated only on transition to
        complete"). Callers still need to flush/commit the provider
        themselves (this only mutates the in-memory attribute).
        """
        was_complete = provider.profile_completion_percentage >= 100
        result = await self.calculate(provider)
        provider.profile_completion_percentage = result.completion_percentage

        if result.complete and not was_complete:
            await self._outbox.enqueue(
                ProviderEvent.PROFILE_COMPLETED,
                {"providerId": str(provider.id), "completionPercentage": result.completion_percentage},
                aggregate_id=provider.id,
            )
        return result
