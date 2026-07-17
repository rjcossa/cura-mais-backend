"""Applicant-facing routes: application lifecycle, sections, documents,
information requests (spec sections 7-9)."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.core.envelope import ErrorEnvelope, success
from app.core.exceptions import PermissionDeniedError
from app.modules.identity.domain.enums import PermissionCode
from app.modules.onboarding.api.deps import (
    CurrentAuth,
    get_application_repo,
    get_application_service,
    get_completeness_service,
    get_document_repo,
    get_document_service,
    get_information_request_repo,
    get_information_request_service,
    get_requirements_service,
)
from app.modules.onboarding.application.application_service import ApplicationService
from app.modules.onboarding.application.completeness_service import CompletenessService
from app.modules.onboarding.application.document_service import DocumentService
from app.modules.onboarding.application.information_request_service import InformationRequestService
from app.modules.onboarding.application.requirements_service import RequirementsService
from app.modules.onboarding.application.schemas import (
    ApplicationDocumentOut,
    ApplicationRequirementsOut,
    ApplicationSummaryOut,
    CompletenessOut,
    ConfirmUploadRequest,
    CreateUploadRequestRequest,
    CreateUploadRequestResponse,
    InformationRequestOut,
    RespondToInformationRequestRequest,
    ResubmitApplicationRequest,
    SectionSummaryOut,
    SubmitApplicationRequest,
    SubmitApplicationResponse,
    UpdateSectionRequest,
    WithdrawApplicationRequest,
)
from app.modules.onboarding.domain.exceptions import OnboardingError

router = APIRouter(
    prefix="/onboarding/me",
    tags=["Onboarding — Applicant"],
    responses={401: {"model": ErrorEnvelope}, 403: {"model": ErrorEnvelope}},
)


def _require_self_permission(auth: CurrentAuth, code: str) -> None:
    if code not in auth.claims.permissions:
        raise PermissionDeniedError()


def _to_summary(application, sections) -> ApplicationSummaryOut:
    step = next((s.section_code for s in sections if s.status != "COMPLETE"), None)
    return ApplicationSummaryOut(
        id=application.id,
        application_number=application.application_number,
        applicant_type=application.applicant_type,
        purpose=application.application_purpose,
        status=application.status,
        completion_percentage=application.completion_percentage,
        submitted_at=application.submitted_at,
        current_step=step,
        sections=[SectionSummaryOut(code=s.section_code, status=s.status) for s in sections],
    )


@router.post("/application", summary="Start a new onboarding application")
async def create_application(
    body: dict,
    auth: CurrentAuth,
    service: Annotated[ApplicationService, Depends(get_application_service)],
    application_repo=Depends(get_application_repo),
):
    _require_self_permission(auth, PermissionCode.ONBOARDING_APPLICATION_UPDATE_SELF.value)
    applicant_type = body.get("applicantType")
    purpose = body.get("purpose", "INITIAL_ONBOARDING")
    full_name = body.get("fullName")

    application = await service.create_application(
        applicant_type=applicant_type,
        applicant_user_id=auth.user.id,
        purpose=purpose,
        applicant_full_name=full_name,
    )
    sections = await application_repo.list_sections(application.id)
    return success(_to_summary(application, sections).model_dump(by_alias=True, mode="json"))


@router.get("/application", summary="Get the current user's onboarding application")
async def get_current_application(
    auth: CurrentAuth,
    service: Annotated[ApplicationService, Depends(get_application_service)],
    application_repo=Depends(get_application_repo),
    applicant_type: Annotated[str | None, Query()] = None,
):
    _require_self_permission(auth, PermissionCode.ONBOARDING_APPLICATION_READ_SELF.value)
    application = await service.get_current_application(auth.user.id, applicant_type)
    if application is None:
        raise OnboardingError.for_code("ONBOARDING_APPLICATION_NOT_FOUND")
    sections = await application_repo.list_sections(application.id)
    return success(_to_summary(application, sections).model_dump(by_alias=True, mode="json"))


@router.get("/application/requirements", summary="Get required sections and documents")
async def get_requirements(
    auth: CurrentAuth,
    service: Annotated[ApplicationService, Depends(get_application_service)],
    requirements: Annotated[RequirementsService, Depends(get_requirements_service)],
):
    _require_self_permission(auth, PermissionCode.ONBOARDING_APPLICATION_READ_SELF.value)
    application = await service.get_current_application(auth.user.id, None)
    if application is None:
        raise OnboardingError.for_code("ONBOARDING_APPLICATION_NOT_FOUND")

    sections = requirements.resolve_sections(application.applicant_type)
    documents = await requirements.resolve_documents(application)

    out = ApplicationRequirementsOut(
        required_sections=[{"code": s.code, "mandatory": s.mandatory} for s in sections],
        required_documents=[
            {
                "documentType": d.document_type,
                "mandatory": d.mandatory,
                "requiresExpiryDate": d.requires_expiry_date,
                "allowedMimeTypes": d.allowed_mime_types,
                "maximumFileSizeBytes": d.maximum_file_size_bytes,
            }
            for d in documents
        ],
    )
    return success(out.model_dump(by_alias=True, mode="json"))


@router.get("/application/completeness", summary="Get application completeness")
async def get_completeness(
    auth: CurrentAuth,
    service: Annotated[ApplicationService, Depends(get_application_service)],
    completeness: Annotated[CompletenessService, Depends(get_completeness_service)],
):
    _require_self_permission(auth, PermissionCode.ONBOARDING_APPLICATION_READ_SELF.value)
    application = await service.get_current_application(auth.user.id, None)
    if application is None:
        raise OnboardingError.for_code("ONBOARDING_APPLICATION_NOT_FOUND")

    result = await completeness.calculate(application)
    out = CompletenessOut(
        complete=result.complete,
        completion_percentage=result.completion_percentage,
        missing_fields=result.missing_fields,
        missing_documents=result.missing_documents,
        invalid_documents=result.invalid_documents,
        expired_documents=result.expired_documents,
    )
    return success(out.model_dump(by_alias=True, mode="json"))


@router.put("/application/sections/{section_code}", summary="Update an application section")
async def update_section(
    section_code: str,
    body: UpdateSectionRequest,
    auth: CurrentAuth,
    service: Annotated[ApplicationService, Depends(get_application_service)],
):
    _require_self_permission(auth, PermissionCode.ONBOARDING_APPLICATION_UPDATE_SELF.value)
    application = await service.get_current_application(auth.user.id, None)
    if application is None:
        raise OnboardingError.for_code("ONBOARDING_APPLICATION_NOT_FOUND")

    section = await service.update_section(application, section_code, body.model_dump(by_alias=True))
    return success({"sectionCode": section.section_code, "status": section.status})


@router.post(
    "/application/submit",
    summary="Submit the application for review",
    responses={422: {"model": ErrorEnvelope, "description": "Application incomplete"}},
)
async def submit_application(
    body: SubmitApplicationRequest,
    auth: CurrentAuth,
    service: Annotated[ApplicationService, Depends(get_application_service)],
):
    _require_self_permission(auth, PermissionCode.ONBOARDING_APPLICATION_SUBMIT_SELF.value)
    application = await service.get_current_application(auth.user.id, None)
    if application is None:
        raise OnboardingError.for_code("ONBOARDING_APPLICATION_NOT_FOUND")

    await service.submit_application(
        application, submission_version=body.submission_version, submitted_by=auth.user.id
    )
    out = SubmitApplicationResponse(
        application_id=application.id,
        application_number=application.application_number,
        status=application.status,
        submitted_at=application.submitted_at,
    )
    return success(out.model_dump(by_alias=True, mode="json"))


@router.post("/application/withdraw", summary="Withdraw the application")
async def withdraw_application(
    body: WithdrawApplicationRequest,
    auth: CurrentAuth,
    service: Annotated[ApplicationService, Depends(get_application_service)],
):
    _require_self_permission(auth, PermissionCode.ONBOARDING_APPLICATION_WITHDRAW_SELF.value)
    application = await service.get_current_application(auth.user.id, None)
    if application is None:
        raise OnboardingError.for_code("ONBOARDING_APPLICATION_NOT_FOUND")

    await service.withdraw_application(application, reason=body.reason, withdrawn_by=auth.user.id)
    return success({"status": application.status})


# --- Information requests (spec 8.7-8.9) --------------------------------------


@router.get("/application/information-requests", summary="List information requests on the application")
async def list_information_requests(
    auth: CurrentAuth,
    app_service: Annotated[ApplicationService, Depends(get_application_service)],
    request_repo=Depends(get_information_request_repo),
):
    _require_self_permission(auth, PermissionCode.ONBOARDING_INFORMATION_REQUEST_READ_SELF.value)
    application = await app_service.get_current_application(auth.user.id, None)
    if application is None:
        raise OnboardingError.for_code("ONBOARDING_APPLICATION_NOT_FOUND")

    requests = await request_repo.list_for_application(application.id)
    results = []
    for r in requests:
        items = await request_repo.list_items(r.id)
        out = InformationRequestOut(
            id=r.id,
            reason_code=r.reason_code,
            message=r.message,
            status=r.status,
            response_due_date=r.response_due_date,
            created_at=r.created_at,
            items=[
                {
                    "id": i.id,
                    "itemType": i.item_type,
                    "documentType": i.document_type,
                    "fieldName": i.field_name,
                    "instruction": i.instruction,
                    "status": i.status,
                }
                for i in items
            ],
        )
        results.append(out.model_dump(by_alias=True, mode="json"))
    return success(results)


@router.post(
    "/application/information-requests/{request_id}/respond", summary="Respond to an information request"
)
async def respond_information_request(
    request_id: uuid.UUID,
    body: RespondToInformationRequestRequest,
    auth: CurrentAuth,
    app_service: Annotated[ApplicationService, Depends(get_application_service)],
    info_service: Annotated[InformationRequestService, Depends(get_information_request_service)],
    request_repo=Depends(get_information_request_repo),
):
    _require_self_permission(auth, PermissionCode.ONBOARDING_INFORMATION_REQUEST_RESPOND_SELF.value)
    application = await app_service.get_current_application(auth.user.id, None)
    if application is None:
        raise OnboardingError.for_code("ONBOARDING_APPLICATION_NOT_FOUND")

    request = await request_repo.get_by_id(request_id)
    if request is None or request.application_id != application.id:
        raise OnboardingError.for_code("ONBOARDING_INFORMATION_REQUEST_NOT_FOUND")

    await info_service.respond(
        application,
        request,
        message=body.message,
        document_ids=body.document_ids,
        updated_fields=body.updated_fields,
        responded_by=auth.user.id,
    )
    return success({"status": request.status})


@router.post("/application/resubmit", summary="Resubmit after satisfying an information request")
async def resubmit_application(
    body: ResubmitApplicationRequest,
    auth: CurrentAuth,
    app_service: Annotated[ApplicationService, Depends(get_application_service)],
    info_service: Annotated[InformationRequestService, Depends(get_information_request_service)],
    request_repo=Depends(get_information_request_repo),
):
    _require_self_permission(auth, PermissionCode.ONBOARDING_APPLICATION_SUBMIT_SELF.value)
    application = await app_service.get_current_application(auth.user.id, None)
    if application is None:
        raise OnboardingError.for_code("ONBOARDING_APPLICATION_NOT_FOUND")

    request = await request_repo.get_by_id(body.information_request_id)
    if request is None or request.application_id != application.id:
        raise OnboardingError.for_code("ONBOARDING_INFORMATION_REQUEST_NOT_FOUND")

    await info_service.resubmit(application, request, resubmitted_by=auth.user.id)
    return success({"status": application.status})


# --- Documents (spec 9) ---------------------------------------------------------


@router.post("/application/documents/upload-request", summary="Request a document upload URL")
async def create_upload_request(
    body: CreateUploadRequestRequest,
    auth: CurrentAuth,
    app_service: Annotated[ApplicationService, Depends(get_application_service)],
    doc_service: Annotated[DocumentService, Depends(get_document_service)],
):
    _require_self_permission(auth, PermissionCode.ONBOARDING_DOCUMENT_MANAGE_SELF.value)
    application = await app_service.get_current_application(auth.user.id, None)
    if application is None:
        raise OnboardingError.for_code("ONBOARDING_APPLICATION_NOT_FOUND")

    application_document, upload = await doc_service.create_upload_request(
        application,
        document_type=body.document_type,
        file_name=body.file_name,
        mime_type=body.mime_type,
        file_size=body.file_size,
    )
    out = CreateUploadRequestResponse(
        application_document_id=application_document.id,
        document_id=upload.document_id,
        upload_url=upload.upload_url,
        expires_at=upload.expires_at,
    )
    return success(out.model_dump(by_alias=True, mode="json"))


@router.post("/application/documents/{application_document_id}/confirm", summary="Confirm a document upload")
async def confirm_upload(
    application_document_id: uuid.UUID,
    body: ConfirmUploadRequest,
    auth: CurrentAuth,
    app_service: Annotated[ApplicationService, Depends(get_application_service)],
    doc_service: Annotated[DocumentService, Depends(get_document_service)],
    document_repo=Depends(get_document_repo),
):
    _require_self_permission(auth, PermissionCode.ONBOARDING_DOCUMENT_MANAGE_SELF.value)
    application = await app_service.get_current_application(auth.user.id, None)
    if application is None:
        raise OnboardingError.for_code("ONBOARDING_APPLICATION_NOT_FOUND")

    document = await document_repo.get_by_id(application_document_id)
    if document is None:
        raise OnboardingError.for_code("ONBOARDING_DOCUMENT_NOT_AVAILABLE")

    document = await doc_service.confirm_upload(
        application,
        document,
        checksum=body.checksum,
        document_number=body.document_number,
        issuing_authority=body.issuing_authority,
        issuing_country=body.issuing_country,
        issue_date=body.issue_date,
        expiry_date=body.expiry_date,
    )
    return success({"processingStatus": document.processing_status})


@router.get("/application/documents", summary="List application documents")
async def list_documents(
    auth: CurrentAuth,
    app_service: Annotated[ApplicationService, Depends(get_application_service)],
    doc_service: Annotated[DocumentService, Depends(get_document_service)],
):
    _require_self_permission(auth, PermissionCode.ONBOARDING_APPLICATION_READ_SELF.value)
    application = await app_service.get_current_application(auth.user.id, None)
    if application is None:
        raise OnboardingError.for_code("ONBOARDING_APPLICATION_NOT_FOUND")

    documents = await doc_service.list_documents(application.id)
    results = [
        ApplicationDocumentOut(
            id=d.id,
            document_id=d.document_id,
            document_type=d.document_type,
            document_number=d.document_number,
            issuing_authority=d.issuing_authority,
            issue_date=d.issue_date,
            expiry_date=d.expiry_date,
            processing_status=d.processing_status,
            review_status=d.review_status,
            current_version=d.current_version,
        ).model_dump(by_alias=True, mode="json")
        for d in documents
    ]
    return success(results)


@router.post("/application/documents/{application_document_id}/replace", summary="Replace a document")
async def replace_document(
    application_document_id: uuid.UUID,
    body: CreateUploadRequestRequest,
    auth: CurrentAuth,
    app_service: Annotated[ApplicationService, Depends(get_application_service)],
    doc_service: Annotated[DocumentService, Depends(get_document_service)],
    document_repo=Depends(get_document_repo),
):
    _require_self_permission(auth, PermissionCode.ONBOARDING_DOCUMENT_MANAGE_SELF.value)
    application = await app_service.get_current_application(auth.user.id, None)
    if application is None:
        raise OnboardingError.for_code("ONBOARDING_APPLICATION_NOT_FOUND")

    old_document = await document_repo.get_by_id(application_document_id)
    if old_document is None:
        raise OnboardingError.for_code("ONBOARDING_DOCUMENT_NOT_AVAILABLE")

    new_document, upload = await doc_service.replace_document(
        application, old_document, file_name=body.file_name, mime_type=body.mime_type, file_size=body.file_size
    )
    out = CreateUploadRequestResponse(
        application_document_id=new_document.id,
        document_id=upload.document_id,
        upload_url=upload.upload_url,
        expires_at=upload.expires_at,
    )
    return success(out.model_dump(by_alias=True, mode="json"))


@router.delete("/application/documents/{application_document_id}", summary="Delete a document")
async def delete_document(
    application_document_id: uuid.UUID,
    auth: CurrentAuth,
    app_service: Annotated[ApplicationService, Depends(get_application_service)],
    doc_service: Annotated[DocumentService, Depends(get_document_service)],
    document_repo=Depends(get_document_repo),
):
    _require_self_permission(auth, PermissionCode.ONBOARDING_DOCUMENT_MANAGE_SELF.value)
    application = await app_service.get_current_application(auth.user.id, None)
    if application is None:
        raise OnboardingError.for_code("ONBOARDING_APPLICATION_NOT_FOUND")

    document = await document_repo.get_by_id(application_document_id)
    if document is None:
        raise OnboardingError.for_code("ONBOARDING_DOCUMENT_NOT_AVAILABLE")

    await doc_service.delete_document(application, document)
    return success({"deleted": True})
