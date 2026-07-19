"""Provider service (offering) management (spec sections 14, 15, 33.5, 37.7).

Named `service_offering_service` rather than `service_service` to avoid
the word "service" doing double duty (the application-layer *class*
pattern vs. the `provider_services` *entity*, a clinical offering like
"General Medical Consultation").
"""

from __future__ import annotations

import datetime
import uuid

from app.modules.providers.application.completeness_service import CompletenessService
from app.modules.providers.domain.enums import DeliveryMode
from app.modules.providers.domain.events import ProviderEvent
from app.modules.providers.domain.exceptions import ProviderError
from app.modules.providers.domain.models import Provider, ProviderService
from app.modules.providers.domain.repositories import LocationRepository, OutboxRepository, ServiceRepository, SpecialityRepository

_PHYSICAL_MODES = {DeliveryMode.IN_PERSON.value, DeliveryMode.HOME_VISIT.value}


class ServiceOfferingService:
    def __init__(
        self,
        service_repo: ServiceRepository,
        speciality_repo: SpecialityRepository,
        location_repo: LocationRepository,
        completeness_service: CompletenessService,
        outbox_repo: OutboxRepository,
    ) -> None:
        self._services = service_repo
        self._specialities = speciality_repo
        self._locations = location_repo
        self._completeness = completeness_service
        self._outbox = outbox_repo

    async def list_for_provider(
        self,
        provider_id: uuid.UUID,
        *,
        status: str | None = None,
        delivery_mode: str | None = None,
        pro_bono: bool | None = None,
        speciality_id: uuid.UUID | None = None,
    ) -> list[ProviderService]:
        return await self._services.list_for_provider(
            provider_id, status=status, delivery_mode=delivery_mode, pro_bono=pro_bono, speciality_id=speciality_id
        )

    async def get_owned(self, provider_id: uuid.UUID, service_id: uuid.UUID) -> ProviderService:
        service = await self._services.get_by_id(service_id)
        if service is None or service.provider_id != provider_id:
            raise ProviderError.for_code("PROVIDER_SERVICE_NOT_FOUND")
        return service

    async def get_delivery_modes(self, service_id: uuid.UUID) -> list[str]:
        return await self._services.list_modes(service_id)

    async def create_service(
        self,
        provider: Provider,
        *,
        service_code: str,
        name: str,
        description: str | None,
        speciality_id: uuid.UUID | None,
        duration_minutes: int,
        price: float | None,
        currency: str | None,
        pro_bono: bool,
        requires_pre_screening: bool,
        minimum_patient_age: int | None,
        maximum_patient_age: int | None,
        delivery_modes: list[str],
        booking_notice_minutes: int,
        cancellation_notice_minutes: int,
    ) -> ProviderService:
        self._validate_price(price, currency, pro_bono)
        if await self._services.code_exists(provider.id, service_code):
            raise ProviderError.for_code("PROVIDER_SERVICE_ALREADY_EXISTS")
        if speciality_id is not None and await self._specialities.get_reference_by_id(speciality_id) is None:
            raise ProviderError.for_code("PROVIDER_SPECIALITY_NOT_FOUND")

        service = ProviderService(
            provider_id=provider.id,
            service_code=service_code,
            name=name,
            description=description,
            speciality_id=speciality_id,
            duration_minutes=duration_minutes,
            price=None if pro_bono else price,
            currency=currency,
            pro_bono=pro_bono,
            requires_pre_screening=requires_pre_screening,
            minimum_patient_age=minimum_patient_age,
            maximum_patient_age=maximum_patient_age,
            booking_notice_minutes=booking_notice_minutes,
            cancellation_notice_minutes=cancellation_notice_minutes,
            status="DRAFT",
        )
        await self._services.add(service)
        if delivery_modes:
            await self._services.replace_modes(service.id, delivery_modes)

        await self._outbox.enqueue(
            ProviderEvent.SERVICE_CREATED,
            {"providerId": str(provider.id), "serviceId": str(service.id), "proBono": pro_bono},
            aggregate_id=provider.id,
        )
        return service

    async def update_service(self, service: ProviderService, *, updates: dict, delivery_modes: list[str] | None) -> ProviderService:
        for field, value in updates.items():
            if hasattr(service, field):
                setattr(service, field, value)
        self._validate_price(service.price, service.currency, service.pro_bono)
        if delivery_modes is not None:
            await self._services.replace_modes(service.id, delivery_modes)
        return service

    async def activate_service(self, provider: Provider, service: ProviderService) -> ProviderService:
        if provider.verification_status != "VERIFIED":
            raise ProviderError.for_code("PROVIDER_NOT_VERIFIED")
        if provider.profile_status == "SUSPENDED":
            raise ProviderError.for_code("PROVIDER_SUSPENDED")
        if provider.profile_status != "ACTIVE":
            raise ProviderError.for_code("PROVIDER_NOT_ACTIVE")
        if service.status == "ACTIVE":
            raise ProviderError.for_code("PROVIDER_SERVICE_ALREADY_ACTIVE")
        if service.status == "ARCHIVED":
            raise ProviderError.for_code("PROVIDER_SERVICE_ALREADY_ARCHIVED")

        self._validate_price(service.price, service.currency, service.pro_bono)

        modes = await self._services.list_modes(service.id)
        if not modes:
            raise ProviderError.for_code("PROVIDER_SERVICE_DELIVERY_MODE_REQUIRED")

        if service.speciality_id is not None:
            speciality = await self._specialities.get_reference_by_id(service.speciality_id)
            assignment = await self._specialities.get_assignment(provider.id, service.speciality_id)
            if speciality is None or not speciality.active or assignment is None:
                raise ProviderError.for_code(
                    "PROVIDER_SERVICE_ACTIVATION_NOT_ALLOWED",
                    "The linked speciality must be active and assigned to the provider.",
                )

        if _PHYSICAL_MODES & set(modes):
            if await self._locations.count_active_physical(provider.id) == 0:
                raise ProviderError.for_code("PROVIDER_SERVICE_LOCATION_REQUIRED")

        service.status = "ACTIVE"
        service.activated_at = datetime.datetime.now(datetime.UTC)

        await self._completeness.refresh(provider)
        await self._outbox.enqueue(
            ProviderEvent.SERVICE_ACTIVATED,
            {"providerId": str(provider.id), "serviceId": str(service.id), "deliveryModes": modes},
            aggregate_id=provider.id,
        )
        return service

    async def deactivate_service(self, provider: Provider, service: ProviderService) -> ProviderService:
        service.status = "INACTIVE"
        service.deactivated_at = datetime.datetime.now(datetime.UTC)
        await self._completeness.refresh(provider)

        await self._outbox.enqueue(
            ProviderEvent.SERVICE_DEACTIVATED,
            {"providerId": str(provider.id), "serviceId": str(service.id)},
            aggregate_id=provider.id,
        )
        return service

    async def archive_service(self, provider: Provider, service: ProviderService) -> ProviderService:
        if service.status == "ARCHIVED":
            raise ProviderError.for_code("PROVIDER_SERVICE_ALREADY_ARCHIVED")
        service.status = "ARCHIVED"
        await self._completeness.refresh(provider)

        await self._outbox.enqueue(
            ProviderEvent.SERVICE_ARCHIVED,
            {"providerId": str(provider.id), "serviceId": str(service.id)},
            aggregate_id=provider.id,
        )
        return service

    async def suspend_all_active(self, provider_id: uuid.UUID) -> list[ProviderService]:
        """Spec 23.5 / 7.4 — "All active services should become
        unavailable for new bookings" when the provider is suspended.
        """
        suspended = []
        for service in await self._services.list_for_provider(provider_id, status="ACTIVE"):
            service.status = "SUSPENDED"
            suspended.append(service)
        return suspended

    @staticmethod
    def _validate_price(price: float | None, currency: str | None, pro_bono: bool) -> None:
        if pro_bono:
            return
        if price is None or price < 0 or not currency:
            raise ProviderError.for_code("PROVIDER_SERVICE_PRICE_INVALID")
