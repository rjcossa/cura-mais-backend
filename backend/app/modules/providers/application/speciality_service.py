"""Reference specialities (medical_specialities) and provider speciality
assignments (spec section 12, 33.4, 37.5).

"A provider must retain at least one speciality before onboarding
submission" (spec 12's rules) is enforced at submission time by Onboarding
itself (via `validateForOnboardingSubmission`, spec 23.1) — this service
allows removing a provider's last speciality freely and lets profile
completeness reflect the gap, the same soft approach spec 37.6 already
prescribes for removing a provider's last consultation language, rather
than hard-blocking the DELETE (spec 37.5 explicitly allows either).
"""

from __future__ import annotations

import datetime
import uuid

from app.modules.providers.application.completeness_service import CompletenessService
from app.modules.providers.domain.events import ProviderEvent
from app.modules.providers.domain.exceptions import ProviderError
from app.modules.providers.domain.models import MedicalSpeciality, Provider, ProviderSpeciality
from app.modules.providers.domain.repositories import OutboxRepository, SpecialityRepository

_VERIFIED_STATUSES = {"VERIFIED", "CONDITIONALLY_VERIFIED"}


class SpecialityService:
    def __init__(
        self, speciality_repo: SpecialityRepository, completeness_service: CompletenessService, outbox_repo: OutboxRepository
    ) -> None:
        self._specialities = speciality_repo
        self._completeness = completeness_service
        self._outbox = outbox_repo

    # --- Reference data (spec 12.1) ---------------------------------------------

    async def list_reference(
        self, *, provider_type: str | None, parent_code: str | None, active: bool | None
    ) -> list[MedicalSpeciality]:
        return await self._specialities.list_reference(provider_type=provider_type, parent_code=parent_code, active=active)

    # --- Provider assignments ------------------------------------------------------

    async def list_for_provider(self, provider_id: uuid.UUID) -> list[ProviderSpeciality]:
        return await self._specialities.list_for_provider(provider_id)

    async def get_owned(self, provider_id: uuid.UUID, provider_speciality_id: uuid.UUID) -> ProviderSpeciality:
        assignment = await self._specialities.get_by_id(provider_speciality_id)
        if assignment is None or assignment.provider_id != provider_id:
            raise ProviderError.for_code("PROVIDER_SPECIALITY_NOT_FOUND")
        return assignment

    async def add_speciality(
        self, provider: Provider, *, speciality_id: uuid.UUID, is_primary: bool, years_of_experience: int | None
    ) -> ProviderSpeciality:
        speciality = await self._specialities.get_reference_by_id(speciality_id)
        if speciality is None or not speciality.active:
            raise ProviderError.for_code("PROVIDER_SPECIALITY_NOT_FOUND")
        if speciality.provider_type != provider.provider_type:
            raise ProviderError.for_code("PROVIDER_SPECIALITY_NOT_ALLOWED")
        if await self._specialities.get_assignment(provider.id, speciality_id) is not None:
            raise ProviderError.for_code("PROVIDER_SPECIALITY_ALREADY_ASSIGNED")

        if is_primary:
            await self._clear_existing_primary(provider.id)

        assignment = ProviderSpeciality(
            provider_id=provider.id,
            speciality_id=speciality_id,
            is_primary=is_primary,
            years_of_experience=years_of_experience,
            verification_status="UNVERIFIED",
        )
        await self._specialities.add(assignment)
        await self._completeness.refresh(provider)

        await self._outbox.enqueue(
            ProviderEvent.SPECIALITY_ADDED,
            {"providerId": str(provider.id), "specialityId": str(speciality_id), "isPrimary": is_primary},
            aggregate_id=provider.id,
        )
        return assignment

    async def update_speciality(
        self, provider: Provider, assignment: ProviderSpeciality, *, years_of_experience: int | None
    ) -> ProviderSpeciality:
        assignment.years_of_experience = years_of_experience
        await self._completeness.refresh(provider)
        return assignment

    async def set_primary(self, provider: Provider, assignment: ProviderSpeciality) -> ProviderSpeciality:
        previous_primary = await self._clear_existing_primary(provider.id, exclude_id=assignment.id)
        if previous_primary is not None:
            # Forces the "clear" UPDATE to hit the DB before the "set"
            # UPDATE below — see RegistrationRepository.flush's docstring
            # for why this ordering matters against the partial unique index.
            await self._specialities.flush()
        assignment.is_primary = True

        triggers_material_change = provider.verification_status in _VERIFIED_STATUSES and (
            assignment.verification_status == "VERIFIED"
            or (previous_primary is not None and previous_primary.verification_status == "VERIFIED")
        )
        if triggers_material_change:
            await self._outbox.enqueue(
                ProviderEvent.PRIMARY_SPECIALITY_CHANGED,
                {"providerId": str(provider.id), "specialityId": str(assignment.speciality_id)},
                aggregate_id=provider.id,
            )
        return assignment

    async def remove_speciality(self, provider: Provider, assignment: ProviderSpeciality) -> None:
        was_primary_verified = assignment.is_primary and assignment.verification_status == "VERIFIED"
        assignment.deleted_at = datetime.datetime.now(datetime.UTC)
        assignment.is_primary = False
        await self._completeness.refresh(provider)

        await self._outbox.enqueue(
            ProviderEvent.SPECIALITY_REMOVED,
            {"providerId": str(provider.id), "specialityId": str(assignment.speciality_id)},
            aggregate_id=provider.id,
        )
        if was_primary_verified and provider.verification_status in _VERIFIED_STATUSES:
            await self._outbox.enqueue(
                ProviderEvent.MATERIAL_CHANGE_DETECTED,
                {"providerId": str(provider.id), "changedFields": ["primarySpeciality"]},
                aggregate_id=provider.id,
            )

    async def _clear_existing_primary(
        self, provider_id: uuid.UUID, *, exclude_id: uuid.UUID | None = None
    ) -> ProviderSpeciality | None:
        current = await self._specialities.get_primary(provider_id)
        if current is not None and current.id != exclude_id:
            current.is_primary = False
            return current
        return None
