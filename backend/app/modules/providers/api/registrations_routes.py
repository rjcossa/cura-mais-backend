"""Professional registration routes (spec section 10)."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends

from app.core.envelope import ErrorEnvelope, success
from app.core.exceptions import PermissionDeniedError
from app.modules.identity.domain.enums import PermissionCode
from app.modules.providers.api.deps import CurrentAuth, DbSession, flush_and_refresh, get_profile_service, get_registration_service
from app.modules.providers.application.profile_service import ProfileService
from app.modules.providers.application.professional_registration_service import ProfessionalRegistrationService
from app.modules.providers.application.schemas import CreateRegistrationRequest, RegistrationOut, UpdateRegistrationRequest

router = APIRouter(
    prefix="/providers/me/registrations",
    tags=["Providers — Self-Service"],
    responses={401: {"model": ErrorEnvelope}, 403: {"model": ErrorEnvelope}},
)


def _require_self_permission(auth: CurrentAuth, code: str) -> None:
    if code not in auth.claims.permissions:
        raise PermissionDeniedError()


def _out(registration) -> dict:
    return RegistrationOut.model_validate(registration, from_attributes=True).model_dump(by_alias=True, mode="json")


@router.get("", summary="List registrations")
async def list_registrations(
    auth: CurrentAuth,
    profile_service: Annotated[ProfileService, Depends(get_profile_service)],
    registration_service: Annotated[ProfessionalRegistrationService, Depends(get_registration_service)],
):
    _require_self_permission(auth, PermissionCode.PROVIDER_REGISTRATION_MANAGE_SELF.value)
    provider = await profile_service.require_by_user_id(auth.user.id)
    registrations = await registration_service.list_for_provider(provider.id)
    return success([_out(r) for r in registrations])


@router.post("", summary="Create a professional registration")
async def create_registration(
    body: CreateRegistrationRequest,
    auth: CurrentAuth,
    profile_service: Annotated[ProfileService, Depends(get_profile_service)],
    registration_service: Annotated[ProfessionalRegistrationService, Depends(get_registration_service)],
):
    _require_self_permission(auth, PermissionCode.PROVIDER_REGISTRATION_MANAGE_SELF.value)
    provider = await profile_service.require_by_user_id(auth.user.id)
    registration = await registration_service.add_registration(
        provider,
        registration_type=body.registration_type,
        registration_number=body.registration_number,
        registration_authority=body.registration_authority,
        registration_country=body.registration_country.upper(),
        issue_date=body.issue_date,
        expiry_date=body.expiry_date,
        is_primary=body.is_primary,
    )
    return success(_out(registration))


@router.patch("/{registration_id}", summary="Update a registration")
async def update_registration(
    registration_id: uuid.UUID,
    body: UpdateRegistrationRequest,
    auth: CurrentAuth,
    db: DbSession,
    profile_service: Annotated[ProfileService, Depends(get_profile_service)],
    registration_service: Annotated[ProfessionalRegistrationService, Depends(get_registration_service)],
):
    _require_self_permission(auth, PermissionCode.PROVIDER_REGISTRATION_MANAGE_SELF.value)
    provider = await profile_service.require_by_user_id(auth.user.id)
    registration = await registration_service.get_owned(provider.id, registration_id)
    registration = await registration_service.update_registration(
        provider, registration, updates=body.model_dump(exclude_unset=True)
    )
    await flush_and_refresh(db, registration)
    return success(_out(registration))


@router.delete("/{registration_id}", summary="Delete a registration")
async def delete_registration(
    registration_id: uuid.UUID,
    auth: CurrentAuth,
    profile_service: Annotated[ProfileService, Depends(get_profile_service)],
    registration_service: Annotated[ProfessionalRegistrationService, Depends(get_registration_service)],
):
    _require_self_permission(auth, PermissionCode.PROVIDER_REGISTRATION_MANAGE_SELF.value)
    provider = await profile_service.require_by_user_id(auth.user.id)
    registration = await registration_service.get_owned(provider.id, registration_id)
    await registration_service.delete_registration(provider, registration)
    return success({"deleted": True})


@router.post("/{registration_id}/set-primary", summary="Set the primary registration")
async def set_primary_registration(
    registration_id: uuid.UUID,
    auth: CurrentAuth,
    db: DbSession,
    profile_service: Annotated[ProfileService, Depends(get_profile_service)],
    registration_service: Annotated[ProfessionalRegistrationService, Depends(get_registration_service)],
):
    _require_self_permission(auth, PermissionCode.PROVIDER_REGISTRATION_MANAGE_SELF.value)
    provider = await profile_service.require_by_user_id(auth.user.id)
    registration = await registration_service.get_owned(provider.id, registration_id)
    registration = await registration_service.set_primary(provider, registration)
    await flush_and_refresh(db, registration)
    return success(_out(registration))
