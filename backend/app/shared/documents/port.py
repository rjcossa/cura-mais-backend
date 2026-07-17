"""Documents module port (Onboarding spec section 21.6) and a mock
adapter standing in for it.

The Documents module (file storage, presigned uploads, malware scanning)
doesn't exist yet as a real module — this mirrors exactly how SMS is
handled in `app/core/notifications.py`: a narrow interface that the real
implementation will satisfy later, with a mock behind it now so the
dependent module (Onboarding) can be built and tested end-to-end today.

**What's simplified in the mock:** real malware scanning and virus/format
validation are asynchronous (can take seconds to minutes); this mock
transitions PENDING_UPLOAD -> AVAILABLE synchronously inside
`confirm_upload`, since there's no real scanning pipeline to wait on. The
port's shape (separate `create_upload_request` / `confirm_upload` calls,
a `get_document_status` poll point) is what makes swapping in a real,
genuinely-async implementation later a matter of implementing this
Protocol differently — Onboarding's application services never assume
synchronous availability.
"""

from __future__ import annotations

import datetime
import uuid
from dataclasses import dataclass
from typing import Protocol


class DocumentStatus:
    PENDING_UPLOAD = "PENDING_UPLOAD"
    UPLOADED = "UPLOADED"
    PROCESSING = "PROCESSING"
    AVAILABLE = "AVAILABLE"
    REJECTED = "REJECTED"
    DELETED = "DELETED"


@dataclass(slots=True)
class UploadRequestResult:
    document_id: uuid.UUID
    upload_url: str
    expires_at: datetime.datetime


@dataclass(slots=True)
class DocumentMetadata:
    document_id: uuid.UUID
    file_name: str
    mime_type: str
    file_size: int
    status: str
    checksum: str | None = None
    uploaded_at: datetime.datetime | None = None


class DocumentPort(Protocol):
    async def create_upload_request(
        self, *, document_type: str, file_name: str, mime_type: str, file_size: int
    ) -> UploadRequestResult: ...

    async def confirm_upload(self, document_id: uuid.UUID, *, checksum: str) -> str:
        """Returns the resulting `DocumentStatus`."""
        ...

    async def get_document_status(self, document_id: uuid.UUID) -> str: ...

    async def get_document_metadata(self, document_id: uuid.UUID) -> DocumentMetadata | None: ...

    async def request_document_deletion(self, document_id: uuid.UUID) -> None: ...


class MockDocumentAdapter:
    """In-memory stand-in for the Documents module. Process-lifetime only
    (not persisted) — fine for local development and tests, since actual
    file bytes are never involved; Onboarding only needs the status
    lifecycle and metadata to drive its own workflow.
    """

    def __init__(self) -> None:
        self._documents: dict[uuid.UUID, DocumentMetadata] = {}

    async def create_upload_request(
        self, *, document_type: str, file_name: str, mime_type: str, file_size: int
    ) -> UploadRequestResult:
        document_id = uuid.uuid4()
        self._documents[document_id] = DocumentMetadata(
            document_id=document_id,
            file_name=file_name,
            mime_type=mime_type,
            file_size=file_size,
            status=DocumentStatus.PENDING_UPLOAD,
        )
        expires_at = datetime.datetime.now(datetime.UTC) + datetime.timedelta(minutes=15)
        return UploadRequestResult(
            document_id=document_id,
            upload_url=f"https://mock-documents.local/upload/{document_id}",
            expires_at=expires_at,
        )

    async def confirm_upload(self, document_id: uuid.UUID, *, checksum: str) -> str:
        doc = self._documents.get(document_id)
        if doc is None:
            raise ValueError(f"Unknown document {document_id}")
        # Real implementation: UPLOADED -> PROCESSING (malware scan queued)
        # -> AVAILABLE/REJECTED asynchronously. Mocked as immediate success.
        doc.checksum = checksum
        doc.uploaded_at = datetime.datetime.now(datetime.UTC)
        doc.status = DocumentStatus.AVAILABLE
        return doc.status

    async def get_document_status(self, document_id: uuid.UUID) -> str:
        doc = self._documents.get(document_id)
        return doc.status if doc else DocumentStatus.DELETED

    async def get_document_metadata(self, document_id: uuid.UUID) -> DocumentMetadata | None:
        return self._documents.get(document_id)

    async def request_document_deletion(self, document_id: uuid.UUID) -> None:
        doc = self._documents.get(document_id)
        if doc is not None:
            doc.status = DocumentStatus.DELETED


_adapter: MockDocumentAdapter | None = None


def get_document_adapter() -> DocumentPort:
    global _adapter
    if _adapter is None:
        _adapter = MockDocumentAdapter()
    return _adapter
