"""Real implementation of `app.shared.provider.port.ProviderPort` —
constructed fresh per call site (same idiom
`onboarding/application/outbox_dispatcher.py` already uses for
`IdentityAdapter`/`RoleService` via its inline `_role_service(session)`
helper), bound to the caller's `AsyncSession` so the activation/suspension
side effects land in the same transaction as the outbox row being
delivered.

`activate_provider` always does a *full* activation (VERIFIED/ACTIVE),
never the conditional variant: confirmed by reading
`onboarding/application/decision_service.py::approve` — it hardcodes
`postApprovalAction: "ACTIVATE"` regardless of whether `conditions` is
non-empty, so `ProviderPort.activate_provider` is the only activation
entry point Onboarding calls through today. `ProfileService`'s
`conditionally_activate_provider` (spec 23.4) is fully implemented and
unit-tested but not reachable from this adapter until Onboarding's own
decision service is changed to distinguish the two cases at this
integration seam — out of scope here (see plan's Integration seam
section).

`user_id` is what Onboarding actually passes as "provider_id" through
this port (see `application_service.py`'s `_INDIVIDUAL_APPLICANT_TYPES`
handling — confirmed by reading it, not assumed) — every method here
resolves the provider by `user_id`, not `providers.id`.
"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.providers.application.completeness_service import CompletenessService
from app.modules.providers.application.profile_service import ProfileService
from app.modules.providers.application.qualification_service import QualificationService
from app.modules.providers.application.professional_registration_service import ProfessionalRegistrationService
from app.modules.providers.application.service_offering_service import ServiceOfferingService
from app.modules.providers.domain.exceptions import ProviderError
from app.modules.providers.domain.models import Provider
from app.modules.providers.infrastructure.repositories import (
    SqlAlchemyLanguageRepository,
    SqlAlchemyLocationRepository,
    SqlAlchemyMediaRepository,
    SqlAlchemyOutboxRepository,
    SqlAlchemyProviderRepository,
    SqlAlchemyQualificationRepository,
    SqlAlchemyRegistrationRepository,
    SqlAlchemyServiceRepository,
    SqlAlchemySpecialityRepository,
)
from app.shared.provider.port import ProviderActivationCall, ProviderProfile  # noqa: F401 - re-exported shape reference


class ProviderPortAdapter:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._provider_repo = SqlAlchemyProviderRepository(session)

        registration_repo = SqlAlchemyRegistrationRepository(session)
        qualification_repo = SqlAlchemyQualificationRepository(session)
        speciality_repo = SqlAlchemySpecialityRepository(session)
        language_repo = SqlAlchemyLanguageRepository(session)
        service_repo = SqlAlchemyServiceRepository(session)
        location_repo = SqlAlchemyLocationRepository(session)
        media_repo = SqlAlchemyMediaRepository(session)
        outbox_repo = SqlAlchemyOutboxRepository(session)

        completeness = CompletenessService(
            registration_repo, qualification_repo, speciality_repo, language_repo, service_repo, media_repo, outbox_repo
        )
        self._profile = ProfileService(self._provider_repo, completeness, outbox_repo)
        self._registrations = ProfessionalRegistrationService(registration_repo, completeness, outbox_repo)
        self._qualifications = QualificationService(qualification_repo, speciality_repo, completeness, outbox_repo)
        self._services = ServiceOfferingService(service_repo, speciality_repo, location_repo, completeness, outbox_repo)

    async def create_provider(
        self, user_id: uuid.UUID, *, provider_type: str, first_name: str, last_name: str, email: str | None = None
    ) -> None:
        await self._profile.create_provider(
            user_id=user_id, provider_type=provider_type, first_name=first_name, last_name=last_name
        )

    async def get_provider_profile(self, provider_id: uuid.UUID) -> ProviderProfile:
        provider = await self._provider_repo.get_by_user_id(provider_id)
        if provider is None:
            return ProviderProfile(provider_id=provider_id, exists=False)
        return ProviderProfile(
            provider_id=provider_id,
            exists=True,
            active=provider.profile_status == "ACTIVE",
            approval_reference=provider.approval_reference,
        )

    async def validate_provider_profile(self, provider_id: uuid.UUID) -> bool:
        return await self._provider_repo.get_by_user_id(provider_id) is not None

    async def activate_provider(self, provider_id: uuid.UUID, *, approval_reference: str) -> None:
        provider = await self._require_by_user_id(provider_id)
        await self._profile.activate_provider(
            provider, approval_reference=approval_reference, approval_valid_until=None,
            source_reference=approval_reference, changed_by=None,
        )
        await self._registrations.mark_all_verified(provider.id, verified_by=None)
        await self._qualifications.mark_all_verified(provider.id, verified_by=None)

    async def suspend_provider(self, provider_id: uuid.UUID, *, reason: str) -> None:
        provider = await self._require_by_user_id(provider_id)
        await self._profile.suspend_provider(
            provider, reason_code=reason, comments=None, source_type="ONBOARDING_DECISION",
            source_reference=None, changed_by=None,
        )
        await self._services.suspend_all_active(provider.id)

    async def reinstate_provider(self, provider_id: uuid.UUID, *, approval_reference: str) -> None:
        provider = await self._require_by_user_id(provider_id)
        await self._profile.reinstate_provider(
            provider, approval_reference=approval_reference, source_reference=approval_reference, changed_by=None
        )

    async def _require_by_user_id(self, user_id: uuid.UUID) -> Provider:
        provider = await self._provider_repo.get_by_user_id(user_id)
        if provider is None:
            raise ProviderError.for_code("PROVIDER_NOT_FOUND", f"No provider record exists for user {user_id}.")
        return provider
