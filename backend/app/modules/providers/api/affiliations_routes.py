"""Institution affiliation routes — self-service side (spec section 17).
Confirm/reject (the institution stand-in) live in `backoffice_routes.py`.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends

from app.core.envelope import ErrorEnvelope, success
from app.core.exceptions import PermissionDeniedError
from app.modules.identity.domain.enums import PermissionCode
from app.modules.providers.api.deps import CurrentAuth, DbSession, flush_and_refresh, get_affiliation_service, get_profile_service
from app.modules.providers.application.affiliation_service import AffiliationService
from app.modules.providers.application.profile_service import ProfileService
from app.modules.providers.application.schemas import AffiliationOut, CreateAffiliationRequest, EndAffiliationRequest, UpdateAffiliationRequest

router = APIRouter(
    prefix="/providers/me/affiliations",
    tags=["Providers — Self-Service"],
    responses={401: {"model": ErrorEnvelope}, 403: {"model": ErrorEnvelope}},
)


def _require_self_permission(auth: CurrentAuth, code: str) -> None:
    if code not in auth.claims.permissions:
        raise PermissionDeniedError()


def _out(affiliation) -> dict:
    return AffiliationOut.model_validate(affiliation, from_attributes=True).model_dump(by_alias=True, mode="json")


@router.get("", summary="List affiliations")
async def list_affiliations(
    auth: CurrentAuth,
    profile_service: Annotated[ProfileService, Depends(get_profile_service)],
    affiliation_service: Annotated[AffiliationService, Depends(get_affiliation_service)],
):
    _require_self_permission(auth, PermissionCode.PROVIDER_AFFILIATION_MANAGE_SELF.value)
    provider = await profile_service.require_by_user_id(auth.user.id)
    affiliations = await affiliation_service.list_for_provider(provider.id)
    return success([_out(a) for a in affiliations])


@router.post("", summary="Create an affiliation request")
async def request_affiliation(
    body: CreateAffiliationRequest,
    auth: CurrentAuth,
    profile_service: Annotated[ProfileService, Depends(get_profile_service)],
    affiliation_service: Annotated[AffiliationService, Depends(get_affiliation_service)],
):
    _require_self_permission(auth, PermissionCode.PROVIDER_AFFILIATION_MANAGE_SELF.value)
    provider = await profile_service.require_by_user_id(auth.user.id)
    affiliation = await affiliation_service.request_affiliation(
        provider,
        institution_id=body.institution_id,
        department_id=body.department_id,
        affiliation_type=body.affiliation_type,
        professional_position=body.professional_position,
        start_date=body.start_date,
        end_date=body.end_date,
        requested_by=auth.user.id,
    )
    return success(_out(affiliation))


@router.patch("/{affiliation_id}", summary="Update an affiliation")
async def update_affiliation(
    affiliation_id: uuid.UUID,
    body: UpdateAffiliationRequest,
    auth: CurrentAuth,
    db: DbSession,
    profile_service: Annotated[ProfileService, Depends(get_profile_service)],
    affiliation_service: Annotated[AffiliationService, Depends(get_affiliation_service)],
):
    _require_self_permission(auth, PermissionCode.PROVIDER_AFFILIATION_MANAGE_SELF.value)
    provider = await profile_service.require_by_user_id(auth.user.id)
    affiliation = await affiliation_service.get_owned(provider.id, affiliation_id)
    affiliation = await affiliation_service.update_affiliation(affiliation, updates=body.model_dump(exclude_unset=True))
    await flush_and_refresh(db, affiliation)
    return success(_out(affiliation))


@router.post("/{affiliation_id}/end", summary="End an affiliation")
async def end_affiliation(
    affiliation_id: uuid.UUID,
    body: EndAffiliationRequest,
    auth: CurrentAuth,
    db: DbSession,
    profile_service: Annotated[ProfileService, Depends(get_profile_service)],
    affiliation_service: Annotated[AffiliationService, Depends(get_affiliation_service)],
):
    _require_self_permission(auth, PermissionCode.PROVIDER_AFFILIATION_MANAGE_SELF.value)
    provider = await profile_service.require_by_user_id(auth.user.id)
    affiliation = await affiliation_service.get_owned(provider.id, affiliation_id)
    affiliation = await affiliation_service.end_affiliation(affiliation, end_date=body.end_date, reason=body.reason)
    await flush_and_refresh(db, affiliation)
    return success(_out(affiliation))
