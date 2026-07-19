"""Self-service profile, completeness, and publication routes (spec
sections 9, 19.1-19.3)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.core.envelope import ErrorEnvelope, success
from app.core.exceptions import PermissionDeniedError
from app.modules.identity.domain.enums import PermissionCode
from app.modules.providers.api.deps import (
    CurrentAuth,
    DbSession,
    flush_and_refresh,
    get_completeness_service,
    get_profile_service,
    get_publication_service,
)
from app.modules.providers.application.completeness_service import CompletenessService
from app.modules.providers.application.profile_service import ProfileService
from app.modules.providers.application.publication_service import PublicationService
from app.modules.providers.application.schemas import (
    CompletenessOut,
    ProviderProfileOut,
    PublishProviderRequest,
    UpdateProviderProfileRequest,
)

router = APIRouter(prefix="/providers/me", tags=["Providers — Self-Service"], responses={401: {"model": ErrorEnvelope}, 403: {"model": ErrorEnvelope}})


def _require_self_permission(auth: CurrentAuth, code: str) -> None:
    if code not in auth.claims.permissions:
        raise PermissionDeniedError()


@router.get("", summary="Get the current provider's profile")
async def get_my_profile(auth: CurrentAuth, service: Annotated[ProfileService, Depends(get_profile_service)]):
    _require_self_permission(auth, PermissionCode.PROVIDER_PROFILE_READ_SELF.value)
    provider = await service.require_by_user_id(auth.user.id)
    return success(ProviderProfileOut.model_validate(provider, from_attributes=True).model_dump(by_alias=True, mode="json"))


@router.patch("", summary="Update the current provider's profile")
async def update_my_profile(
    body: UpdateProviderProfileRequest,
    auth: CurrentAuth,
    db: DbSession,
    service: Annotated[ProfileService, Depends(get_profile_service)],
):
    _require_self_permission(auth, PermissionCode.PROVIDER_PROFILE_UPDATE_SELF.value)
    provider = await service.require_by_user_id(auth.user.id)
    updates = body.model_dump(exclude={"version"}, exclude_unset=True)
    provider, _material_change = await service.update_profile(provider, updates=updates, expected_version=body.version)
    await flush_and_refresh(db, provider)
    return success(ProviderProfileOut.model_validate(provider, from_attributes=True).model_dump(by_alias=True, mode="json"))


@router.get("/completeness", summary="Get the current provider's profile completeness")
async def get_my_completeness(
    auth: CurrentAuth,
    profile_service: Annotated[ProfileService, Depends(get_profile_service)],
    completeness_service: Annotated[CompletenessService, Depends(get_completeness_service)],
):
    _require_self_permission(auth, PermissionCode.PROVIDER_PROFILE_READ_SELF.value)
    provider = await profile_service.require_by_user_id(auth.user.id)
    result = await completeness_service.calculate(provider)
    return success(
        CompletenessOut(
            complete=result.complete,
            completion_percentage=result.completion_percentage,
            missing_fields=result.missing_fields,
            missing_relationships=result.missing_relationships,
            missing_requirements=result.missing_requirements,
            publication_eligible=result.publication_eligible,
        ).model_dump(by_alias=True, mode="json")
    )


@router.post("/publication/publish", summary="Request publication of the current provider's profile")
async def publish_my_profile(
    body: PublishProviderRequest,
    auth: CurrentAuth,
    db: DbSession,
    profile_service: Annotated[ProfileService, Depends(get_profile_service)],
    publication_service: Annotated[PublicationService, Depends(get_publication_service)],
):
    _require_self_permission(auth, PermissionCode.PROVIDER_PUBLICATION_MANAGE_SELF.value)
    provider = await profile_service.require_by_user_id(auth.user.id)
    provider = await publication_service.publish(provider, performed_by=auth.user.id)
    await flush_and_refresh(db, provider)
    return success(ProviderProfileOut.model_validate(provider, from_attributes=True).model_dump(by_alias=True, mode="json"))


@router.post("/publication/unpublish", summary="Unpublish the current provider's profile")
async def unpublish_my_profile(
    auth: CurrentAuth,
    db: DbSession,
    profile_service: Annotated[ProfileService, Depends(get_profile_service)],
    publication_service: Annotated[PublicationService, Depends(get_publication_service)],
):
    _require_self_permission(auth, PermissionCode.PROVIDER_PUBLICATION_MANAGE_SELF.value)
    provider = await profile_service.require_by_user_id(auth.user.id)
    provider = await publication_service.unpublish(provider, performed_by=auth.user.id)
    await flush_and_refresh(db, provider)
    return success(ProviderProfileOut.model_validate(provider, from_attributes=True).model_dump(by_alias=True, mode="json"))
