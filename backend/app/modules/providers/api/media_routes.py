"""Profile photo / media routes (spec section 18)."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends

from app.core.envelope import ErrorEnvelope, success
from app.core.exceptions import PermissionDeniedError
from app.modules.identity.domain.enums import PermissionCode
from app.modules.providers.api.deps import CurrentAuth, get_media_service, get_profile_service
from app.modules.providers.application.media_service import MediaService
from app.modules.providers.application.profile_service import ProfileService
from app.modules.providers.application.schemas import ConfirmMediaUploadRequest, CreateMediaUploadRequest, MediaOut, MediaUploadRequestOut

router = APIRouter(
    prefix="/providers/me/media",
    tags=["Providers — Self-Service"],
    responses={401: {"model": ErrorEnvelope}, 403: {"model": ErrorEnvelope}},
)


def _require_self_permission(auth: CurrentAuth, code: str) -> None:
    if code not in auth.claims.permissions:
        raise PermissionDeniedError()


@router.post("/profile-photo/upload-request", summary="Create a profile-photo upload request")
async def create_profile_photo_upload_request(
    body: CreateMediaUploadRequest,
    auth: CurrentAuth,
    profile_service: Annotated[ProfileService, Depends(get_profile_service)],
    media_service: Annotated[MediaService, Depends(get_media_service)],
):
    _require_self_permission(auth, PermissionCode.PROVIDER_PROFILE_UPDATE_SELF.value)
    provider = await profile_service.require_by_user_id(auth.user.id)
    media, upload = await media_service.create_profile_photo_upload_request(
        provider, file_name=body.file_name, mime_type=body.mime_type, file_size=body.file_size
    )
    out = MediaUploadRequestOut(media_id=media.id, document_id=upload.document_id, upload_url=upload.upload_url, expires_at=upload.expires_at)
    return success(out.model_dump(by_alias=True, mode="json"))


@router.post("/profile-photo/{media_id}/confirm", summary="Confirm a profile-photo upload")
async def confirm_profile_photo_upload(
    media_id: uuid.UUID,
    body: ConfirmMediaUploadRequest,
    auth: CurrentAuth,
    profile_service: Annotated[ProfileService, Depends(get_profile_service)],
    media_service: Annotated[MediaService, Depends(get_media_service)],
):
    _require_self_permission(auth, PermissionCode.PROVIDER_PROFILE_UPDATE_SELF.value)
    provider = await profile_service.require_by_user_id(auth.user.id)
    media = await media_service.get_owned(provider.id, media_id)
    media = await media_service.confirm_profile_photo_upload(provider, media, checksum=body.checksum)
    return success(MediaOut.model_validate(media, from_attributes=True).model_dump(by_alias=True, mode="json"))
