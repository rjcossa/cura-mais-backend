"""Back-office decision routes: verification checks (spec 14),
information requests (spec 15), and approve/conditionally-approve/
reject/suspend (spec 16-17)."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends

from app.core.envelope import ErrorEnvelope, success
from app.modules.identity.api.deps import require_permission
from app.modules.onboarding.api.deps import (
    CurrentAuth,
    get_application_repo,
    get_decision_service,
    get_information_request_service,
    get_verification_repo,
    get_verification_service,
)
from app.modules.onboarding.application.decision_service import DecisionService
from app.modules.onboarding.application.information_request_service import InformationRequestService
from app.modules.onboarding.application.schemas import (
    ApproveApplicationRequest,
    CompleteVerificationCheckRequest,
    ConditionallyApproveApplicationRequest,
    CreateInformationRequestRequest,
    CreateVerificationCheckRequest,
    RejectApplicationRequest,
    SuspendApplicationRequest,
    VerificationCheckOut,
)
from app.modules.onboarding.application.verification_service import VerificationService
from app.modules.onboarding.domain.exceptions import OnboardingError

router = APIRouter(
    prefix="/back-office/onboarding/applications/{application_id}",
    tags=["Onboarding — Decisions"],
    responses={401: {"model": ErrorEnvelope}, 403: {"model": ErrorEnvelope}},
)


async def _load_application(application_id: uuid.UUID, application_repo):
    application = await application_repo.get_by_id(application_id)
    if application is None:
        raise OnboardingError.for_code("ONBOARDING_APPLICATION_NOT_FOUND")
    return application


# --- Verification checks (spec 14) ------------------------------------------------


@router.post(
    "/verification-checks",
    summary="Create a verification check",
    dependencies=[Depends(require_permission("ONBOARDING_VERIFICATION_EXECUTE"))],
)
async def create_verification_check(
    application_id: uuid.UUID,
    body: CreateVerificationCheckRequest,
    auth: CurrentAuth,
    service: Annotated[VerificationService, Depends(get_verification_service)],
    application_repo=Depends(get_application_repo),
):
    application = await _load_application(application_id, application_repo)
    check = await service.create_check(
        application,
        check_type=body.check_type,
        provider=body.provider,
        subject_reference=body.subject_reference,
        initiated_by=auth.user.id,
    )
    out = VerificationCheckOut(
        id=check.id,
        check_type=check.check_type,
        provider=check.provider,
        subject_reference=check.subject_reference,
        status=check.status,
        result=check.result,
        verified_data=check.verified_data,
        initiated_at=check.initiated_at,
        completed_at=check.completed_at,
    )
    return success(out.model_dump(by_alias=True, mode="json"))


@router.post(
    "/verification-checks/{check_id}/complete",
    summary="Complete a verification check",
    dependencies=[Depends(require_permission("ONBOARDING_VERIFICATION_EXECUTE"))],
)
async def complete_verification_check(
    application_id: uuid.UUID,
    check_id: uuid.UUID,
    body: CompleteVerificationCheckRequest,
    service: Annotated[VerificationService, Depends(get_verification_service)],
    application_repo=Depends(get_application_repo),
    verification_repo=Depends(get_verification_repo),
):
    application = await _load_application(application_id, application_repo)
    check = await verification_repo.get_by_id(check_id)
    if check is None or check.application_id != application_id:
        raise OnboardingError.for_code("ONBOARDING_VERIFICATION_CHECK_NOT_FOUND")

    await service.complete_check(
        application,
        check,
        result=body.result,
        external_reference=body.external_reference,
        verified_data=body.verified_data,
        comments=body.comments,
    )
    return success({"status": check.status, "result": check.result})


# --- Information requests (spec 15) -------------------------------------------------


@router.post(
    "/information-requests",
    summary="Create an information request",
    dependencies=[Depends(require_permission("ONBOARDING_INFORMATION_REQUEST"))],
)
async def create_information_request(
    application_id: uuid.UUID,
    body: CreateInformationRequestRequest,
    auth: CurrentAuth,
    service: Annotated[InformationRequestService, Depends(get_information_request_service)],
    application_repo=Depends(get_application_repo),
):
    application = await _load_application(application_id, application_repo)
    request = await service.create_request(
        application,
        reason_code=body.reason_code,
        message=body.message,
        response_due_date=body.response_due_date,
        items=[i.model_dump(by_alias=False) for i in body.items],
        requested_by=auth.user.id,
    )
    return success({"requestId": str(request.id), "status": request.status})


# --- Decisions (spec 16-17) -----------------------------------------------------------


@router.post(
    "/approve",
    summary="Approve an application",
    dependencies=[Depends(require_permission("ONBOARDING_APPLICATION_APPROVE"))],
    responses={
        403: {"model": ErrorEnvelope, "description": "Maker-checker violation"},
        409: {"model": ErrorEnvelope, "description": "Approval preconditions not met"},
    },
)
async def approve_application(
    application_id: uuid.UUID,
    body: ApproveApplicationRequest,
    auth: CurrentAuth,
    service: Annotated[DecisionService, Depends(get_decision_service)],
    application_repo=Depends(get_application_repo),
):
    application = await _load_application(application_id, application_repo)
    decision = await service.approve(
        application,
        decision_comments=body.decision_comments,
        approval_valid_until=body.approval_valid_until,
        conditions=[],
        approved_by=auth.user.id,
    )
    return success({"decisionId": str(decision.id), "status": application.status})


@router.post(
    "/conditionally-approve",
    summary="Conditionally approve an application",
    dependencies=[Depends(require_permission("ONBOARDING_APPLICATION_CONDITIONALLY_APPROVE"))],
)
async def conditionally_approve_application(
    application_id: uuid.UUID,
    body: ConditionallyApproveApplicationRequest,
    auth: CurrentAuth,
    service: Annotated[DecisionService, Depends(get_decision_service)],
    application_repo=Depends(get_application_repo),
):
    application = await _load_application(application_id, application_repo)
    decision = await service.approve(
        application,
        decision_comments=body.decision_comments,
        approval_valid_until=body.approval_valid_until,
        conditions=[c.model_dump(by_alias=True, mode="json") for c in body.conditions],
        approved_by=auth.user.id,
    )
    return success({"decisionId": str(decision.id), "status": application.status})


@router.post(
    "/reject",
    summary="Reject an application",
    dependencies=[Depends(require_permission("ONBOARDING_APPLICATION_REJECT"))],
)
async def reject_application(
    application_id: uuid.UUID,
    body: RejectApplicationRequest,
    auth: CurrentAuth,
    service: Annotated[DecisionService, Depends(get_decision_service)],
    application_repo=Depends(get_application_repo),
):
    application = await _load_application(application_id, application_repo)
    decision = await service.reject(
        application,
        reason_code=body.reason_code,
        decision_comments=body.decision_comments,
        allow_new_application=body.allow_new_application,
        cooling_off_period_days=body.cooling_off_period_days,
        rejected_by=auth.user.id,
    )
    return success({"decisionId": str(decision.id), "status": application.status})


@router.post(
    "/suspend",
    summary="Suspend an approved applicant/provider",
    dependencies=[Depends(require_permission("ONBOARDING_APPLICANT_SUSPEND"))],
)
async def suspend_application(
    application_id: uuid.UUID,
    body: SuspendApplicationRequest,
    auth: CurrentAuth,
    service: Annotated[DecisionService, Depends(get_decision_service)],
    application_repo=Depends(get_application_repo),
):
    application = await _load_application(application_id, application_repo)
    decision = await service.suspend(
        application, reason_code=body.reason_code, comments=body.comments, suspended_by=auth.user.id
    )
    return success({"decisionId": str(decision.id), "status": application.status})
