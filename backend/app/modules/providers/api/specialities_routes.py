"""Speciality routes: reference data (spec 12.1) and provider assignments
(spec 12.2-12.6). Two routers since the reference-data endpoint lives
under `/reference-data`, not `/providers/me`.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.core.envelope import ErrorEnvelope, success
from app.core.exceptions import PermissionDeniedError
from app.modules.identity.domain.enums import PermissionCode
from app.modules.providers.api.deps import CurrentAuth, DbSession, flush_and_refresh, get_profile_service, get_speciality_service
from app.modules.providers.application.profile_service import ProfileService
from app.modules.providers.application.schemas import AddSpecialityRequest, ProviderSpecialityOut, SpecialityReferenceOut, UpdateSpecialityRequest
from app.modules.providers.application.speciality_service import SpecialityService

reference_router = APIRouter(prefix="/reference-data", tags=["Providers — Reference Data"])

router = APIRouter(
    prefix="/providers/me/specialities",
    tags=["Providers — Self-Service"],
    responses={401: {"model": ErrorEnvelope}, 403: {"model": ErrorEnvelope}},
)


def _require_self_permission(auth: CurrentAuth, code: str) -> None:
    if code not in auth.claims.permissions:
        raise PermissionDeniedError()


def _out(assignment) -> dict:
    return ProviderSpecialityOut.model_validate(assignment, from_attributes=True).model_dump(by_alias=True, mode="json")


@reference_router.get("/provider-specialities", summary="List reference specialities")
async def list_reference_specialities(
    service: Annotated[SpecialityService, Depends(get_speciality_service)],
    provider_type: Annotated[str | None, Query(alias="providerType")] = None,
    parent_code: Annotated[str | None, Query(alias="parentCode")] = None,
    active: Annotated[bool | None, Query()] = None,
):
    specialities = await service.list_reference(provider_type=provider_type, parent_code=parent_code, active=active)
    return success(
        [SpecialityReferenceOut.model_validate(s, from_attributes=True).model_dump(by_alias=True, mode="json") for s in specialities]
    )


@router.get("", summary="List provider specialities")
async def list_specialities(
    auth: CurrentAuth,
    profile_service: Annotated[ProfileService, Depends(get_profile_service)],
    speciality_service: Annotated[SpecialityService, Depends(get_speciality_service)],
):
    _require_self_permission(auth, PermissionCode.PROVIDER_SPECIALITY_MANAGE_SELF.value)
    provider = await profile_service.require_by_user_id(auth.user.id)
    assignments = await speciality_service.list_for_provider(provider.id)
    return success([_out(a) for a in assignments])


@router.post("", summary="Add a provider speciality")
async def add_speciality(
    body: AddSpecialityRequest,
    auth: CurrentAuth,
    profile_service: Annotated[ProfileService, Depends(get_profile_service)],
    speciality_service: Annotated[SpecialityService, Depends(get_speciality_service)],
):
    _require_self_permission(auth, PermissionCode.PROVIDER_SPECIALITY_MANAGE_SELF.value)
    provider = await profile_service.require_by_user_id(auth.user.id)
    assignment = await speciality_service.add_speciality(
        provider, speciality_id=body.speciality_id, is_primary=body.is_primary, years_of_experience=body.years_of_experience
    )
    return success(_out(assignment))


@router.patch("/{provider_speciality_id}", summary="Update a provider speciality")
async def update_speciality(
    provider_speciality_id: uuid.UUID,
    body: UpdateSpecialityRequest,
    auth: CurrentAuth,
    db: DbSession,
    profile_service: Annotated[ProfileService, Depends(get_profile_service)],
    speciality_service: Annotated[SpecialityService, Depends(get_speciality_service)],
):
    _require_self_permission(auth, PermissionCode.PROVIDER_SPECIALITY_MANAGE_SELF.value)
    provider = await profile_service.require_by_user_id(auth.user.id)
    assignment = await speciality_service.get_owned(provider.id, provider_speciality_id)
    assignment = await speciality_service.update_speciality(provider, assignment, years_of_experience=body.years_of_experience)
    await flush_and_refresh(db, assignment)
    return success(_out(assignment))


@router.post("/{provider_speciality_id}/set-primary", summary="Set the primary speciality")
async def set_primary_speciality(
    provider_speciality_id: uuid.UUID,
    auth: CurrentAuth,
    db: DbSession,
    profile_service: Annotated[ProfileService, Depends(get_profile_service)],
    speciality_service: Annotated[SpecialityService, Depends(get_speciality_service)],
):
    _require_self_permission(auth, PermissionCode.PROVIDER_SPECIALITY_MANAGE_SELF.value)
    provider = await profile_service.require_by_user_id(auth.user.id)
    assignment = await speciality_service.get_owned(provider.id, provider_speciality_id)
    assignment = await speciality_service.set_primary(provider, assignment)
    await flush_and_refresh(db, assignment)
    return success(_out(assignment))


@router.delete("/{provider_speciality_id}", summary="Remove a provider speciality")
async def remove_speciality(
    provider_speciality_id: uuid.UUID,
    auth: CurrentAuth,
    profile_service: Annotated[ProfileService, Depends(get_profile_service)],
    speciality_service: Annotated[SpecialityService, Depends(get_speciality_service)],
):
    _require_self_permission(auth, PermissionCode.PROVIDER_SPECIALITY_MANAGE_SELF.value)
    provider = await profile_service.require_by_user_id(auth.user.id)
    assignment = await speciality_service.get_owned(provider.id, provider_speciality_id)
    await speciality_service.remove_speciality(provider, assignment)
    return success({"removed": True})
