"""Qualification routes (spec section 11)."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends

from app.core.envelope import ErrorEnvelope, success
from app.core.exceptions import PermissionDeniedError
from app.modules.identity.domain.enums import PermissionCode
from app.modules.providers.api.deps import CurrentAuth, DbSession, flush_and_refresh, get_profile_service, get_qualification_service
from app.modules.providers.application.profile_service import ProfileService
from app.modules.providers.application.qualification_service import QualificationService
from app.modules.providers.application.schemas import CreateQualificationRequest, QualificationOut, UpdateQualificationRequest

router = APIRouter(
    prefix="/providers/me/qualifications",
    tags=["Providers — Self-Service"],
    responses={401: {"model": ErrorEnvelope}, 403: {"model": ErrorEnvelope}},
)


def _require_self_permission(auth: CurrentAuth, code: str) -> None:
    if code not in auth.claims.permissions:
        raise PermissionDeniedError()


def _out(qualification) -> dict:
    return QualificationOut.model_validate(qualification, from_attributes=True).model_dump(by_alias=True, mode="json")


@router.get("", summary="List qualifications")
async def list_qualifications(
    auth: CurrentAuth,
    profile_service: Annotated[ProfileService, Depends(get_profile_service)],
    qualification_service: Annotated[QualificationService, Depends(get_qualification_service)],
):
    _require_self_permission(auth, PermissionCode.PROVIDER_QUALIFICATION_MANAGE_SELF.value)
    provider = await profile_service.require_by_user_id(auth.user.id)
    qualifications = await qualification_service.list_for_provider(provider.id)
    return success([_out(q) for q in qualifications])


@router.post("", summary="Create a qualification")
async def create_qualification(
    body: CreateQualificationRequest,
    auth: CurrentAuth,
    profile_service: Annotated[ProfileService, Depends(get_profile_service)],
    qualification_service: Annotated[QualificationService, Depends(get_qualification_service)],
):
    _require_self_permission(auth, PermissionCode.PROVIDER_QUALIFICATION_MANAGE_SELF.value)
    provider = await profile_service.require_by_user_id(auth.user.id)
    qualification = await qualification_service.add_qualification(
        provider,
        qualification_type=body.qualification_type,
        qualification_name=body.qualification_name,
        institution_name=body.institution_name,
        institution_country=body.institution_country,
        start_date=body.start_date,
        completion_date=body.completion_date,
        speciality_id=body.speciality_id,
    )
    return success(_out(qualification))


@router.patch("/{qualification_id}", summary="Update a qualification")
async def update_qualification(
    qualification_id: uuid.UUID,
    body: UpdateQualificationRequest,
    auth: CurrentAuth,
    db: DbSession,
    profile_service: Annotated[ProfileService, Depends(get_profile_service)],
    qualification_service: Annotated[QualificationService, Depends(get_qualification_service)],
):
    _require_self_permission(auth, PermissionCode.PROVIDER_QUALIFICATION_MANAGE_SELF.value)
    provider = await profile_service.require_by_user_id(auth.user.id)
    qualification = await qualification_service.get_owned(provider.id, qualification_id)
    qualification = await qualification_service.update_qualification(
        provider, qualification, updates=body.model_dump(exclude_unset=True)
    )
    await flush_and_refresh(db, qualification)
    return success(_out(qualification))


@router.delete("/{qualification_id}", summary="Delete a qualification")
async def delete_qualification(
    qualification_id: uuid.UUID,
    auth: CurrentAuth,
    profile_service: Annotated[ProfileService, Depends(get_profile_service)],
    qualification_service: Annotated[QualificationService, Depends(get_qualification_service)],
):
    _require_self_permission(auth, PermissionCode.PROVIDER_QUALIFICATION_MANAGE_SELF.value)
    provider = await profile_service.require_by_user_id(auth.user.id)
    qualification = await qualification_service.get_owned(provider.id, qualification_id)
    await qualification_service.delete_qualification(provider, qualification)
    return success({"deleted": True})
