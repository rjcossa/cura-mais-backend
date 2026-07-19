"""Provider service (offering) routes (spec section 14)."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.core.envelope import ErrorEnvelope, success
from app.core.exceptions import PermissionDeniedError
from app.modules.identity.domain.enums import PermissionCode
from app.modules.providers.api.deps import CurrentAuth, DbSession, flush_and_refresh, get_profile_service, get_service_offering_service
from app.modules.providers.application.profile_service import ProfileService
from app.modules.providers.application.schemas import CreateServiceRequest, ServiceOut, UpdateServiceRequest
from app.modules.providers.application.service_offering_service import ServiceOfferingService

router = APIRouter(
    prefix="/providers/me/services",
    tags=["Providers — Self-Service"],
    responses={401: {"model": ErrorEnvelope}, 403: {"model": ErrorEnvelope}},
)


def _require_self_permission(auth: CurrentAuth, code: str) -> None:
    if code not in auth.claims.permissions:
        raise PermissionDeniedError()


async def _out(service, service_offering_service: ServiceOfferingService) -> dict:
    modes = await service_offering_service.get_delivery_modes(service.id)
    out = ServiceOut.model_validate(service, from_attributes=True)
    out.delivery_modes = modes
    return out.model_dump(by_alias=True, mode="json")


@router.get("", summary="List services")
async def list_services(
    auth: CurrentAuth,
    profile_service: Annotated[ProfileService, Depends(get_profile_service)],
    service_offering_service: Annotated[ServiceOfferingService, Depends(get_service_offering_service)],
    status: Annotated[str | None, Query()] = None,
    delivery_mode: Annotated[str | None, Query(alias="deliveryMode")] = None,
    pro_bono: Annotated[bool | None, Query(alias="proBono")] = None,
    speciality_id: Annotated[uuid.UUID | None, Query(alias="specialityId")] = None,
):
    _require_self_permission(auth, PermissionCode.PROVIDER_SERVICE_MANAGE_SELF.value)
    provider = await profile_service.require_by_user_id(auth.user.id)
    services = await service_offering_service.list_for_provider(
        provider.id, status=status, delivery_mode=delivery_mode, pro_bono=pro_bono, speciality_id=speciality_id
    )
    return success([await _out(s, service_offering_service) for s in services])


@router.post("", summary="Create a service")
async def create_service(
    body: CreateServiceRequest,
    auth: CurrentAuth,
    profile_service: Annotated[ProfileService, Depends(get_profile_service)],
    service_offering_service: Annotated[ServiceOfferingService, Depends(get_service_offering_service)],
):
    _require_self_permission(auth, PermissionCode.PROVIDER_SERVICE_MANAGE_SELF.value)
    provider = await profile_service.require_by_user_id(auth.user.id)
    service = await service_offering_service.create_service(
        provider,
        service_code=body.service_code,
        name=body.name,
        description=body.description,
        speciality_id=body.speciality_id,
        duration_minutes=body.duration_minutes,
        price=body.price,
        currency=body.currency,
        pro_bono=body.pro_bono,
        requires_pre_screening=body.requires_pre_screening,
        minimum_patient_age=body.minimum_patient_age,
        maximum_patient_age=body.maximum_patient_age,
        delivery_modes=body.delivery_modes,
        booking_notice_minutes=body.booking_notice_minutes,
        cancellation_notice_minutes=body.cancellation_notice_minutes,
    )
    return success(await _out(service, service_offering_service))


@router.get("/{service_id}", summary="Get a service")
async def get_service(
    service_id: uuid.UUID,
    auth: CurrentAuth,
    profile_service: Annotated[ProfileService, Depends(get_profile_service)],
    service_offering_service: Annotated[ServiceOfferingService, Depends(get_service_offering_service)],
):
    _require_self_permission(auth, PermissionCode.PROVIDER_SERVICE_MANAGE_SELF.value)
    provider = await profile_service.require_by_user_id(auth.user.id)
    service = await service_offering_service.get_owned(provider.id, service_id)
    return success(await _out(service, service_offering_service))


@router.patch("/{service_id}", summary="Update a service")
async def update_service(
    service_id: uuid.UUID,
    body: UpdateServiceRequest,
    auth: CurrentAuth,
    db: DbSession,
    profile_service: Annotated[ProfileService, Depends(get_profile_service)],
    service_offering_service: Annotated[ServiceOfferingService, Depends(get_service_offering_service)],
):
    _require_self_permission(auth, PermissionCode.PROVIDER_SERVICE_MANAGE_SELF.value)
    provider = await profile_service.require_by_user_id(auth.user.id)
    service = await service_offering_service.get_owned(provider.id, service_id)
    updates = body.model_dump(exclude={"delivery_modes"}, exclude_unset=True)
    service = await service_offering_service.update_service(service, updates=updates, delivery_modes=body.delivery_modes)
    await flush_and_refresh(db, service)
    return success(await _out(service, service_offering_service))


@router.post("/{service_id}/activate", summary="Activate a service")
async def activate_service(
    service_id: uuid.UUID,
    auth: CurrentAuth,
    db: DbSession,
    profile_service: Annotated[ProfileService, Depends(get_profile_service)],
    service_offering_service: Annotated[ServiceOfferingService, Depends(get_service_offering_service)],
):
    _require_self_permission(auth, PermissionCode.PROVIDER_SERVICE_MANAGE_SELF.value)
    provider = await profile_service.require_by_user_id(auth.user.id)
    service = await service_offering_service.get_owned(provider.id, service_id)
    service = await service_offering_service.activate_service(provider, service)
    await flush_and_refresh(db, service)
    return success(await _out(service, service_offering_service))


@router.post("/{service_id}/deactivate", summary="Deactivate a service")
async def deactivate_service(
    service_id: uuid.UUID,
    auth: CurrentAuth,
    db: DbSession,
    profile_service: Annotated[ProfileService, Depends(get_profile_service)],
    service_offering_service: Annotated[ServiceOfferingService, Depends(get_service_offering_service)],
):
    _require_self_permission(auth, PermissionCode.PROVIDER_SERVICE_MANAGE_SELF.value)
    provider = await profile_service.require_by_user_id(auth.user.id)
    service = await service_offering_service.get_owned(provider.id, service_id)
    service = await service_offering_service.deactivate_service(provider, service)
    await flush_and_refresh(db, service)
    return success(await _out(service, service_offering_service))


@router.post("/{service_id}/archive", summary="Archive a service")
async def archive_service(
    service_id: uuid.UUID,
    auth: CurrentAuth,
    db: DbSession,
    profile_service: Annotated[ProfileService, Depends(get_profile_service)],
    service_offering_service: Annotated[ServiceOfferingService, Depends(get_service_offering_service)],
):
    _require_self_permission(auth, PermissionCode.PROVIDER_SERVICE_MANAGE_SELF.value)
    provider = await profile_service.require_by_user_id(auth.user.id)
    service = await service_offering_service.get_owned(provider.id, service_id)
    service = await service_offering_service.archive_service(provider, service)
    await flush_and_refresh(db, service)
    return success(await _out(service, service_offering_service))
