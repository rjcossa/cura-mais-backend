"""Professional registration management (spec section 10, 33.2, 37.3)."""

from __future__ import annotations

import datetime
import uuid

from app.modules.providers.application.completeness_service import CompletenessService
from app.modules.providers.domain.events import ProviderEvent
from app.modules.providers.domain.exceptions import ProviderError
from app.modules.providers.domain.models import Provider, ProviderProfessionalRegistration
from app.modules.providers.domain.repositories import OutboxRepository, RegistrationRepository

_VERIFIED_STATUSES = {"VERIFIED", "CONDITIONALLY_VERIFIED"}
_MATERIAL_REGISTRATION_FIELDS = {
    "registration_type",
    "registration_number",
    "registration_authority",
    "registration_country",
    "issue_date",
    "expiry_date",
}


class ProfessionalRegistrationService:
    def __init__(
        self,
        registration_repo: RegistrationRepository,
        completeness_service: CompletenessService,
        outbox_repo: OutboxRepository,
    ) -> None:
        self._registrations = registration_repo
        self._completeness = completeness_service
        self._outbox = outbox_repo

    async def list_for_provider(self, provider_id: uuid.UUID) -> list[ProviderProfessionalRegistration]:
        return await self._registrations.list_for_provider(provider_id)

    async def get_owned(self, provider_id: uuid.UUID, registration_id: uuid.UUID) -> ProviderProfessionalRegistration:
        registration = await self._registrations.get_by_id(registration_id)
        if registration is None or registration.provider_id != provider_id:
            raise ProviderError.for_code("PROVIDER_REGISTRATION_NOT_FOUND")
        return registration

    async def add_registration(
        self,
        provider: Provider,
        *,
        registration_type: str,
        registration_number: str,
        registration_authority: str,
        registration_country: str,
        issue_date: datetime.date | None,
        expiry_date: datetime.date | None,
        is_primary: bool,
    ) -> ProviderProfessionalRegistration:
        self._validate_dates(issue_date, expiry_date)

        existing = await self._registrations.find_by_reference(
            registration_country, registration_authority, registration_number
        )
        if existing is not None:
            raise ProviderError.for_code("PROVIDER_REGISTRATION_ALREADY_EXISTS")

        if is_primary:
            await self._clear_existing_primary(provider.id)

        registration = ProviderProfessionalRegistration(
            provider_id=provider.id,
            registration_type=registration_type,
            registration_number=registration_number,
            registration_authority=registration_authority,
            registration_country=registration_country,
            issue_date=issue_date,
            expiry_date=expiry_date,
            is_primary=is_primary,
            registration_status="ACTIVE",
            verification_status="UNVERIFIED",
        )
        await self._registrations.add(registration)
        await self._completeness.refresh(provider)

        await self._outbox.enqueue(
            ProviderEvent.REGISTRATION_ADDED,
            {"providerId": str(provider.id), "registrationId": str(registration.id), "isPrimary": is_primary},
            aggregate_id=provider.id,
        )
        return registration

    async def update_registration(
        self, provider: Provider, registration: ProviderProfessionalRegistration, *, updates: dict
    ) -> ProviderProfessionalRegistration:
        if registration.decision_locked:
            raise ProviderError.for_code("PROVIDER_REGISTRATION_LOCKED")

        changed = {f for f, v in updates.items() if hasattr(registration, f) and getattr(registration, f) != v}
        if not changed:
            return registration

        material = bool(changed & _MATERIAL_REGISTRATION_FIELDS)
        if registration.verification_status == "VERIFIED" and material:
            return await self._supersede(provider, registration, updates)

        for field, value in updates.items():
            if hasattr(registration, field):
                setattr(registration, field, value)
        self._validate_dates(registration.issue_date, registration.expiry_date)

        await self._completeness.refresh(provider)
        await self._outbox.enqueue(
            ProviderEvent.REGISTRATION_UPDATED,
            {"providerId": str(provider.id), "registrationId": str(registration.id)},
            aggregate_id=provider.id,
        )
        return registration

    async def _supersede(
        self, provider: Provider, old: ProviderProfessionalRegistration, updates: dict
    ) -> ProviderProfessionalRegistration:
        new = ProviderProfessionalRegistration(
            provider_id=provider.id,
            registration_type=updates.get("registration_type", old.registration_type),
            registration_number=updates.get("registration_number", old.registration_number),
            registration_authority=updates.get("registration_authority", old.registration_authority),
            registration_country=updates.get("registration_country", old.registration_country),
            issue_date=updates.get("issue_date", old.issue_date),
            expiry_date=updates.get("expiry_date", old.expiry_date),
            is_primary=old.is_primary,
            registration_status="ACTIVE",
            verification_status="UNVERIFIED",
            supersedes_registration_id=old.id,
        )
        self._validate_dates(new.issue_date, new.expiry_date)

        old.registration_status = "SUPERSEDED"
        old.is_primary = False
        await self._registrations.add(new)
        await self._completeness.refresh(provider)

        await self._outbox.enqueue(
            ProviderEvent.MATERIAL_CHANGE_DETECTED,
            {
                "providerId": str(provider.id),
                "changedFields": ["registrationNumber", "registrationAuthority"],
                "supersededRegistrationId": str(old.id),
                "newRegistrationId": str(new.id),
            },
            aggregate_id=provider.id,
        )
        return new

    async def delete_registration(self, provider: Provider, registration: ProviderProfessionalRegistration) -> None:
        if registration.decision_locked:
            raise ProviderError.for_code("PROVIDER_REGISTRATION_LOCKED")
        if registration.verification_status != "UNVERIFIED":
            raise ProviderError.for_code(
                "PROVIDER_REGISTRATION_LOCKED",
                "Verified registrations cannot be deleted — supersede or deactivate them instead.",
            )
        registration.deleted_at = datetime.datetime.now(datetime.UTC)
        await self._completeness.refresh(provider)

    async def set_primary(
        self, provider: Provider, registration: ProviderProfessionalRegistration
    ) -> ProviderProfessionalRegistration:
        previous_primary = await self._clear_existing_primary(provider.id, exclude_id=registration.id)
        if previous_primary is not None:
            # See RegistrationRepository.flush's docstring: without this,
            # the two UPDATEs can transiently violate
            # ux_provider_primary_registration within the same flush.
            await self._registrations.flush()
        registration.is_primary = True

        triggers_material_change = provider.verification_status in _VERIFIED_STATUSES and (
            registration.verification_status == "VERIFIED"
            or (previous_primary is not None and previous_primary.verification_status == "VERIFIED")
        )
        if triggers_material_change:
            await self._outbox.enqueue(
                ProviderEvent.MATERIAL_CHANGE_DETECTED,
                {"providerId": str(provider.id), "changedFields": ["primaryRegistration"]},
                aggregate_id=provider.id,
            )
        return registration

    async def mark_all_verified(self, provider_id: uuid.UUID, *, verified_by: uuid.UUID | None) -> None:
        """Spec 23.3 step 8 — invoked by the onboarding-activation
        orchestration in `infrastructure/provider_port_adapter.py`.
        """
        now = datetime.datetime.now(datetime.UTC)
        for registration in await self._registrations.list_for_provider(provider_id):
            if registration.verification_status in ("UNVERIFIED", "PENDING") and registration.registration_status == "ACTIVE":
                registration.verification_status = "VERIFIED"
                registration.verified_at = now
                registration.verified_by = verified_by

    async def _clear_existing_primary(
        self, provider_id: uuid.UUID, *, exclude_id: uuid.UUID | None = None
    ) -> ProviderProfessionalRegistration | None:
        current = await self._registrations.get_active_primary(provider_id)
        if current is not None and current.id != exclude_id:
            current.is_primary = False
            return current
        return None

    @staticmethod
    def _validate_dates(issue_date: datetime.date | None, expiry_date: datetime.date | None) -> None:
        if issue_date and expiry_date and expiry_date < issue_date:
            raise ProviderError.for_code("PROVIDER_REGISTRATION_INVALID", "Expiry date cannot precede the issue date.")
