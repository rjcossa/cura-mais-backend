"""Consultation language routes (spec section 13)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.core.envelope import ErrorEnvelope, success
from app.core.exceptions import PermissionDeniedError
from app.modules.identity.domain.enums import PermissionCode
from app.modules.providers.api.deps import CurrentAuth, DbSession, flush_and_refresh, get_language_service, get_profile_service
from app.modules.providers.application.language_service import LanguageService
from app.modules.providers.application.profile_service import ProfileService
from app.modules.providers.application.schemas import AddLanguageRequest, LanguageOut, UpdateLanguageRequest

router = APIRouter(
    prefix="/providers/me/languages",
    tags=["Providers — Self-Service"],
    responses={401: {"model": ErrorEnvelope}, 403: {"model": ErrorEnvelope}},
)


def _require_self_permission(auth: CurrentAuth, code: str) -> None:
    if code not in auth.claims.permissions:
        raise PermissionDeniedError()


def _out(language) -> dict:
    return LanguageOut.model_validate(language, from_attributes=True).model_dump(by_alias=True, mode="json")


@router.get("", summary="List consultation languages")
async def list_languages(
    auth: CurrentAuth,
    profile_service: Annotated[ProfileService, Depends(get_profile_service)],
    language_service: Annotated[LanguageService, Depends(get_language_service)],
):
    _require_self_permission(auth, PermissionCode.PROVIDER_LANGUAGE_MANAGE_SELF.value)
    provider = await profile_service.require_by_user_id(auth.user.id)
    languages = await language_service.list_for_provider(provider.id)
    return success([_out(lang) for lang in languages])


@router.post("", summary="Add a consultation language")
async def add_language(
    body: AddLanguageRequest,
    auth: CurrentAuth,
    profile_service: Annotated[ProfileService, Depends(get_profile_service)],
    language_service: Annotated[LanguageService, Depends(get_language_service)],
):
    _require_self_permission(auth, PermissionCode.PROVIDER_LANGUAGE_MANAGE_SELF.value)
    provider = await profile_service.require_by_user_id(auth.user.id)
    language = await language_service.add_language(
        provider, language_code=body.language_code, proficiency=body.proficiency, can_consult=body.can_consult
    )
    return success(_out(language))


@router.patch("/{language_code}", summary="Update a consultation language")
async def update_language(
    language_code: str,
    body: UpdateLanguageRequest,
    auth: CurrentAuth,
    db: DbSession,
    profile_service: Annotated[ProfileService, Depends(get_profile_service)],
    language_service: Annotated[LanguageService, Depends(get_language_service)],
):
    _require_self_permission(auth, PermissionCode.PROVIDER_LANGUAGE_MANAGE_SELF.value)
    provider = await profile_service.require_by_user_id(auth.user.id)
    language = await language_service.get_owned(provider.id, language_code)
    language = await language_service.update_language(provider, language, proficiency=body.proficiency, can_consult=body.can_consult)
    await flush_and_refresh(db, language)
    return success(_out(language))


@router.delete("/{language_code}", summary="Remove a consultation language")
async def remove_language(
    language_code: str,
    auth: CurrentAuth,
    profile_service: Annotated[ProfileService, Depends(get_profile_service)],
    language_service: Annotated[LanguageService, Depends(get_language_service)],
):
    _require_self_permission(auth, PermissionCode.PROVIDER_LANGUAGE_MANAGE_SELF.value)
    provider = await profile_service.require_by_user_id(auth.user.id)
    language = await language_service.get_owned(provider.id, language_code)
    await language_service.remove_language(provider, language)
    return success({"removed": True})
