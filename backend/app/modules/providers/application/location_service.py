"""Practice location management (spec section 16, 33.6, 37.8).

"Primary" is treated as a physical-location-only concept, matching the
partial unique index `ux_provider_primary_location`'s own
`location_type <> 'VIRTUAL'` predicate (spec 30.9) — a VIRTUAL location
can never be set primary.
"""

from __future__ import annotations

import datetime
import uuid

from app.modules.providers.domain.enums import DeliveryMode, LocationType
from app.modules.providers.domain.events import ProviderEvent
from app.modules.providers.domain.exceptions import ProviderError
from app.modules.providers.domain.models import Provider, ProviderLocation
from app.modules.providers.domain.repositories import LocationRepository, OutboxRepository, ServiceRepository

_ADDRESS_FIELDS = {"address_line_1", "address_line_2", "city", "province", "postal_code", "country_code", "latitude", "longitude"}
_PHYSICAL_MODES = {DeliveryMode.IN_PERSON.value, DeliveryMode.HOME_VISIT.value}


class LocationService:
    def __init__(self, location_repo: LocationRepository, service_repo: ServiceRepository, outbox_repo: OutboxRepository) -> None:
        self._locations = location_repo
        self._services = service_repo
        self._outbox = outbox_repo

    async def list_for_provider(self, provider_id: uuid.UUID) -> list[ProviderLocation]:
        return await self._locations.list_for_provider(provider_id)

    async def get_owned(self, provider_id: uuid.UUID, location_id: uuid.UUID) -> ProviderLocation:
        location = await self._locations.get_by_id(location_id)
        if location is None or location.provider_id != provider_id:
            raise ProviderError.for_code("PROVIDER_LOCATION_NOT_FOUND")
        return location

    async def add_location(
        self,
        provider: Provider,
        *,
        location_type: str,
        name: str,
        address_line_1: str | None,
        address_line_2: str | None,
        city: str | None,
        province: str | None,
        postal_code: str | None,
        country_code: str | None,
        latitude: float | None,
        longitude: float | None,
        contact_number: str | None,
        wheelchair_accessible: bool | None,
        parking_available: bool | None,
        is_primary: bool,
    ) -> ProviderLocation:
        if location_type not in {t.value for t in LocationType}:
            raise ProviderError.for_code("PROVIDER_LOCATION_INVALID", "Unsupported location type.")
        self._validate_coordinates(latitude, longitude)

        if location_type == LocationType.VIRTUAL.value:
            if is_primary:
                raise ProviderError.for_code("PROVIDER_LOCATION_INVALID", "A virtual location cannot be set as primary.")
            address_line_1 = address_line_2 = city = province = postal_code = country_code = None
            latitude = longitude = None

        if is_primary:
            await self._clear_existing_primary(provider.id)

        location = ProviderLocation(
            provider_id=provider.id,
            location_type=location_type,
            name=name,
            address_line_1=address_line_1,
            address_line_2=address_line_2,
            city=city,
            province=province,
            postal_code=postal_code,
            country_code=country_code,
            latitude=latitude,
            longitude=longitude,
            contact_number=contact_number,
            wheelchair_accessible=wheelchair_accessible,
            parking_available=parking_available,
            is_primary=is_primary,
        )
        await self._locations.add(location)

        await self._outbox.enqueue(
            ProviderEvent.LOCATION_ADDED,
            {"providerId": str(provider.id), "locationId": str(location.id), "locationType": location_type},
            aggregate_id=provider.id,
        )
        return location

    async def update_location(self, provider: Provider, location: ProviderLocation, *, updates: dict) -> ProviderLocation:
        if location.institution_id is not None and (set(updates) & _ADDRESS_FIELDS or "name" in updates):
            raise ProviderError.for_code("PROVIDER_INSTITUTION_LOCATION_NOT_EDITABLE")

        for field, value in updates.items():
            if hasattr(location, field):
                setattr(location, field, value)
        self._validate_coordinates(location.latitude, location.longitude)

        await self._outbox.enqueue(
            ProviderEvent.LOCATION_UPDATED,
            {"providerId": str(provider.id), "locationId": str(location.id)},
            aggregate_id=provider.id,
        )
        return location

    async def set_primary(self, provider: Provider, location: ProviderLocation) -> ProviderLocation:
        if location.location_type == LocationType.VIRTUAL.value:
            raise ProviderError.for_code("PROVIDER_LOCATION_INVALID", "A virtual location cannot be set as primary.")
        await self._clear_existing_primary(provider.id, exclude_id=location.id)
        # See RegistrationRepository.flush's docstring: without this, the
        # "clear" and "set" UPDATEs can transiently violate
        # ux_provider_primary_location within the same flush.
        await self._locations.flush()
        location.is_primary = True
        return location

    async def deactivate_location(self, provider: Provider, location: ProviderLocation) -> ProviderLocation:
        if location.active and location.location_type != LocationType.VIRTUAL.value:
            remaining = await self._locations.count_active_physical(provider.id)
            if remaining <= 1:
                # An `await` inside a generator expression passed to
                # `any()` silently makes it an async generator, which
                # `any()` can't consume (it needs a plain iterable) —
                # confirmed by hitting this directly, not assumed.
                requires_physical = False
                for active_service in await self._services.list_for_provider(provider.id, status="ACTIVE"):
                    modes = await self._services.list_modes(active_service.id)
                    if _PHYSICAL_MODES & set(modes):
                        requires_physical = True
                        break
                if requires_physical:
                    raise ProviderError.for_code("PROVIDER_LOCATION_IN_USE")

        location.active = False
        location.is_primary = False

        await self._outbox.enqueue(
            ProviderEvent.LOCATION_DEACTIVATED,
            {"providerId": str(provider.id), "locationId": str(location.id)},
            aggregate_id=provider.id,
        )
        return location

    async def _clear_existing_primary(self, provider_id: uuid.UUID, *, exclude_id: uuid.UUID | None = None) -> None:
        current = await self._locations.get_primary(provider_id)
        if current is not None and current.id != exclude_id:
            current.is_primary = False

    @staticmethod
    def _validate_coordinates(latitude: float | None, longitude: float | None) -> None:
        if latitude is not None and not (-90 <= latitude <= 90):
            raise ProviderError.for_code("PROVIDER_LOCATION_INVALID", "Latitude must be between -90 and 90.")
        if longitude is not None and not (-180 <= longitude <= 180):
            raise ProviderError.for_code("PROVIDER_LOCATION_INVALID", "Longitude must be between -180 and 180.")
