"""Document upload-request/confirm/replace/delete (spec section 9). File
storage/scanning itself is delegated to the Documents module port
(`app.shared.documents.port`) — see that module's docstring for what's
mocked.
"""

from __future__ import annotations

import datetime
import uuid

from app.modules.onboarding.application.requirements_service import RequirementsService
from app.modules.onboarding.domain.enums import ApplicationStatus
from app.modules.onboarding.domain.exceptions import OnboardingError
from app.modules.onboarding.domain.models import OnboardingApplication, OnboardingApplicationDocument
from app.modules.onboarding.domain.repositories import ApplicationDocumentRepository
from app.shared.documents.port import DocumentPort

_EDITABLE_STATUSES = {
    ApplicationStatus.DRAFT.value,
    ApplicationStatus.ADDITIONAL_INFORMATION_REQUIRED.value,
    ApplicationStatus.RESUBMITTED.value,
}


class DocumentService:
    def __init__(
        self,
        document_repo: ApplicationDocumentRepository,
        requirements_service: RequirementsService,
        document_port: DocumentPort,
    ) -> None:
        self._documents = document_repo
        self._requirements = requirements_service
        self._document_port = document_port

    async def create_upload_request(
        self,
        application: OnboardingApplication,
        *,
        document_type: str,
        file_name: str,
        mime_type: str,
        file_size: int,
    ):
        self._assert_editable(application)

        resolved = await self._requirements.resolve_documents(application)
        requirement = next((r for r in resolved if r.document_type == document_type), None)
        if requirement is None:
            raise OnboardingError.for_code("ONBOARDING_DOCUMENT_TYPE_NOT_ALLOWED")
        if mime_type not in requirement.allowed_mime_types:
            raise OnboardingError.for_code("ONBOARDING_DOCUMENT_MIME_TYPE_NOT_ALLOWED")
        if file_size > requirement.maximum_file_size_bytes:
            raise OnboardingError.for_code("ONBOARDING_DOCUMENT_FILE_TOO_LARGE")

        upload = await self._document_port.create_upload_request(
            document_type=document_type, file_name=file_name, mime_type=mime_type, file_size=file_size
        )

        application_document = OnboardingApplicationDocument(
            application_id=application.id,
            document_id=upload.document_id,
            document_type=document_type,
            processing_status="PENDING_UPLOAD",
            satisfies_requirement_id=requirement.requirement_id,
        )
        await self._documents.add(application_document)

        return application_document, upload

    async def confirm_upload(
        self,
        application: OnboardingApplication,
        application_document: OnboardingApplicationDocument,
        *,
        checksum: str,
        document_number: str | None,
        issuing_authority: str | None,
        issuing_country: str | None,
        issue_date,
        expiry_date,
    ) -> OnboardingApplicationDocument:
        self._assert_editable(application)
        if application_document.application_id != application.id:
            raise OnboardingError.for_code("ONBOARDING_DOCUMENT_NOT_AVAILABLE")

        status = await self._document_port.confirm_upload(application_document.document_id, checksum=checksum)

        application_document.processing_status = status
        application_document.document_number = document_number
        application_document.issuing_authority = issuing_authority
        application_document.issuing_country = issuing_country
        application_document.issue_date = issue_date
        application_document.expiry_date = expiry_date
        if status == "REJECTED":
            application_document.review_status = "REJECTED"

        return application_document

    async def list_documents(self, application_id: uuid.UUID) -> list[OnboardingApplicationDocument]:
        return await self._documents.list_current(application_id)

    async def replace_document(
        self,
        application: OnboardingApplication,
        old_document: OnboardingApplicationDocument,
        *,
        file_name: str,
        mime_type: str,
        file_size: int,
    ):
        self._assert_editable(application)
        if old_document.locked_by_decision:
            raise OnboardingError.for_code("ONBOARDING_DOCUMENT_LOCKED")

        new_document, upload = await self.create_upload_request(
            application,
            document_type=old_document.document_type,
            file_name=file_name,
            mime_type=mime_type,
            file_size=file_size,
        )
        new_document.supersedes_application_document_id = old_document.id
        old_document.current_version = False
        old_document.processing_status = "SUPERSEDED"

        return new_document, upload

    async def delete_document(
        self, application: OnboardingApplication, document: OnboardingApplicationDocument
    ) -> None:
        self._assert_editable(application)
        if document.locked_by_decision:
            raise OnboardingError.for_code("ONBOARDING_DOCUMENT_LOCKED")

        await self._document_port.request_document_deletion(document.document_id)
        document.processing_status = "DELETED"
        document.current_version = False
        document.deleted_at = datetime.datetime.now(datetime.UTC)

    @staticmethod
    def _assert_editable(application: OnboardingApplication) -> None:
        if application.status not in _EDITABLE_STATUSES:
            raise OnboardingError.for_code("ONBOARDING_APPLICATION_NOT_EDITABLE")
