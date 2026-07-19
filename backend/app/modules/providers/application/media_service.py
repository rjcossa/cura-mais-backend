"""Profile photo / media management (spec section 18). Storage and
malware scanning are delegated to the Documents module port
(`app.shared.documents.port`) — same shared port and mock
`onboarding/application/document_service.py` already uses, not a
per-module reimplementation.

Moderation is set to `NOT_REQUIRED` on confirm rather than left `PENDING`
forever: there's no real moderation queue in this codebase to resolve a
`PENDING` row (spec 18.3's "may require moderation" is conditional, and
nothing implements that condition today) — documented here rather than
silently modelled as if a moderation pipeline existed.
"""

from __future__ import annotations

import uuid

from app.modules.providers.domain.events import ProviderEvent
from app.modules.providers.domain.exceptions import ProviderError
from app.modules.providers.domain.models import Provider, ProviderProfileMedia
from app.modules.providers.domain.repositories import MediaRepository, OutboxRepository
from app.shared.documents.port import DocumentPort

_ALLOWED_PHOTO_MIME_TYPES = {"image/jpeg", "image/png"}
_MAX_PHOTO_SIZE_BYTES = 10 * 1024 * 1024


class MediaService:
    def __init__(self, media_repo: MediaRepository, document_port: DocumentPort, outbox_repo: OutboxRepository) -> None:
        self._media = media_repo
        self._documents = document_port
        self._outbox = outbox_repo

    async def get_owned(self, provider_id: uuid.UUID, media_id: uuid.UUID):
        media = await self._media.get_by_id(media_id)
        if media is None or media.provider_id != provider_id:
            raise ProviderError.for_code("PROVIDER_MEDIA_NOT_FOUND")
        return media

    async def create_profile_photo_upload_request(
        self, provider: Provider, *, file_name: str, mime_type: str, file_size: int
    ):
        if mime_type not in _ALLOWED_PHOTO_MIME_TYPES:
            raise ProviderError.for_code("PROVIDER_MEDIA_INVALID", "Only JPEG/PNG images are accepted for profile photos.")
        if file_size > _MAX_PHOTO_SIZE_BYTES:
            raise ProviderError.for_code("PROVIDER_MEDIA_INVALID", "The file exceeds the maximum allowed size.")

        upload = await self._documents.create_upload_request(
            document_type="PROFILE_PHOTO", file_name=file_name, mime_type=mime_type, file_size=file_size
        )
        media = ProviderProfileMedia(
            provider_id=provider.id,
            document_id=upload.document_id,
            media_type="PROFILE_PHOTO",
            processing_status="PENDING_UPLOAD",
            moderation_status="PENDING",
            active=False,
        )
        await self._media.add(media)
        return media, upload

    async def confirm_profile_photo_upload(
        self, provider: Provider, media: ProviderProfileMedia, *, checksum: str
    ) -> ProviderProfileMedia:
        status = await self._documents.confirm_upload(media.document_id, checksum=checksum)
        media.processing_status = status
        if status == "AVAILABLE":
            media.active = True
            media.moderation_status = "NOT_REQUIRED"
            await self._media.deactivate_others(provider.id, "PROFILE_PHOTO", media.id)
        return media
