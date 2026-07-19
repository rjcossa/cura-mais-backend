"""Practice location routes (spec section 16)."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends

from app.core.envelope import ErrorEnvelope, success
from app.core.exceptions import PermissionDeniedError
from app.modules.identity.domain.enums import PermissionCode
from app.modules.providers.api.deps import CurrentAuth, DbSession, flush_and_refresh, get_location_service, get_profile_service
from app.modules.providers.application.location_service import LocationService
from app.modules.providers.application.profile_service import ProfileService
from app.modules.providers.application.schemas import CreateLocationRequest, LocationOut, UpdateLocationRequest

router = APIRouter(
    prefix="/providers/me/locations",
    tags=["Providers — Self-Service"],
    responses={401: {"model": ErrorEnvelope}, 403: {"model": ErrorEnvelope}},
)


def _require_self_permission(auth: CurrentAuth, code: str) -> None:
    if code not in auth.claims.permissions:
        raise PermissionDeniedError()


def _out(location) -> dict:
    return LocationOut.model_validate(location, from_attributes=True).model_dump(by_alias=True, mode="json")


@router.get("", summary="List locations")
async def list_locations(
    auth: CurrentAuth,
    profile_service: Annotated[ProfileService, Depends(get_profile_service)],
    location_service: Annotated[LocationService, Depends(get_location_service)],
):
    _require_self_permission(auth, PermissionCode.PROVIDER_LOCATION_MANAGE_SELF.value)
    provider = await profile_service.require_by_user_id(auth.user.id)
    locations = await location_service.list_for_provider(provider.id)
    return success([_out(loc) for loc in locations])


@router.post("", summary="Create a location")
async def create_location(
    body: CreateLocationRequest,
    auth: CurrentAuth,
    profile_service: Annotated[ProfileService, Depends(get_profile_service)],
    location_service: Annotated[LocationService, Depends(get_location_service)],
):
    _require_self_permission(auth, PermissionCode.PROVIDER_LOCATION_MANAGE_SELF.value)
    provider = await profile_service.require_by_user_id(auth.user.id)
    location = await location_service.add_location(
        provider,
        location_type=body.location_type,
        name=body.name,
        address_line_1=body.address_line_1,
        address_line_2=body.address_line_2,
        city=body.city,
        province=body.province,
        postal_code=body.postal_code,
        country_code=body.country_code,
        latitude=body.latitude,
        longitude=body.longitude,
        contact_number=body.contact_number,
        wheelchair_accessible=body.wheelchair_accessible,
        parking_available=body.parking_available,
        is_primary=body.is_primary,
    )
    return success(_out(location))


@router.patch("/{location_id}", summary="Update a location")
async def update_location(
    location_id: uuid.UUID,
    body: UpdateLocationRequest,
    auth: CurrentAuth,
    db: DbSession,
    profile_service: Annotated[ProfileService, Depends(get_profile_service)],
    location_service: Annotated[LocationService, Depends(get_location_service)],
):
    _require_self_permission(auth, PermissionCode.PROVIDER_LOCATION_MANAGE_SELF.value)
    provider = await profile_service.require_by_user_id(auth.user.id)
    location = await location_service.get_owned(provider.id, location_id)
    location = await location_service.update_location(provider, location, updates=body.model_dump(exclude_unset=True))
    await flush_and_refresh(db, location)
    return success(_out(location))


@router.post("/{location_id}/set-primary", summary="Set the primary location")
async def set_primary_location(
    location_id: uuid.UUID,
    auth: CurrentAuth,
    db: DbSession,
    profile_service: Annotated[ProfileService, Depends(get_profile_service)],
    location_service: Annotated[LocationService, Depends(get_location_service)],
):
    _require_self_permission(auth, PermissionCode.PROVIDER_LOCATION_MANAGE_SELF.value)
    provider = await profile_service.require_by_user_id(auth.user.id)
    location = await location_service.get_owned(provider.id, location_id)
    location = await location_service.set_primary(provider, location)
    await flush_and_refresh(db, location)
    return success(_out(location))


@router.post("/{location_id}/deactivate", summary="Deactivate a location")
async def deactivate_location(
    location_id: uuid.UUID,
    auth: CurrentAuth,
    db: DbSession,
    profile_service: Annotated[ProfileService, Depends(get_profile_service)],
    location_service: Annotated[LocationService, Depends(get_location_service)],
):
    _require_self_permission(auth, PermissionCode.PROVIDER_LOCATION_MANAGE_SELF.value)
    provider = await profile_service.require_by_user_id(auth.user.id)
    location = await location_service.get_owned(provider.id, location_id)
    location = await location_service.deactivate_location(provider, location)
    await flush_and_refresh(db, location)
    return success(_out(location))
