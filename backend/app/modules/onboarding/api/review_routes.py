"""Review lifecycle routes (spec section 13)."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends

from app.core.envelope import ErrorEnvelope, success
from app.modules.identity.api.deps import require_permission
from app.modules.onboarding.api.deps import (
    CurrentAuth,
    get_application_repo,
    get_document_repo,
    get_review_repo,
    get_review_service,
)
from app.modules.onboarding.application.review_service import ReviewService
from app.modules.onboarding.application.schemas import (
    ChecklistItemOut,
    CompleteReviewRequest,
    ReviewDocumentRequest,
    ReviewOut,
    StartReviewRequest,
    UpdateChecklistItemRequest,
)
from app.modules.onboarding.domain.exceptions import OnboardingError

router = APIRouter(
    prefix="/back-office/onboarding/applications/{application_id}",
    tags=["Onboarding — Review"],
    responses={401: {"model": ErrorEnvelope}, 403: {"model": ErrorEnvelope}},
)


async def _load_application(application_id: uuid.UUID, application_repo):
    application = await application_repo.get_by_id(application_id)
    if application is None:
        raise OnboardingError.for_code("ONBOARDING_APPLICATION_NOT_FOUND")
    return application


@router.post(
    "/reviews/start",
    summary="Start a review",
    dependencies=[Depends(require_permission("ONBOARDING_REVIEW_START"))],
)
async def start_review(
    application_id: uuid.UUID,
    body: StartReviewRequest,
    auth: CurrentAuth,
    service: Annotated[ReviewService, Depends(get_review_service)],
    application_repo=Depends(get_application_repo),
):
    application = await _load_application(application_id, application_repo)
    review = await service.start_review(application, review_type=body.review_type, reviewer_id=auth.user.id)
    return success({"reviewId": str(review.id), "status": review.status})


@router.get(
    "/reviews/{review_id}",
    summary="Get a review with its checklist",
    dependencies=[Depends(require_permission("ONBOARDING_APPLICATION_READ"))],
)
async def get_review(
    application_id: uuid.UUID,
    review_id: uuid.UUID,
    review_repo=Depends(get_review_repo),
):
    review = await review_repo.get_by_id(review_id)
    if review is None or review.application_id != application_id:
        raise OnboardingError.for_code("ONBOARDING_APPLICATION_NOT_FOUND")

    items = await review_repo.list_checklist_items(review_id)
    out = ReviewOut(
        id=review.id,
        review_type=review.review_type,
        status=review.status,
        recommendation=review.recommendation,
        comments=review.comments,
        started_at=review.started_at,
        completed_at=review.completed_at,
        checklist_items=[
            ChecklistItemOut(
                id=i.id,
                item_code=i.item_code,
                item_description=i.item_description,
                mandatory=i.mandatory,
                result=i.result,
                comments=i.comments,
                evidence_reference=i.evidence_reference,
            )
            for i in items
        ],
    )
    return success(out.model_dump(by_alias=True, mode="json"))


@router.patch(
    "/reviews/{review_id}/checklist-items/{item_id}",
    summary="Update a checklist item",
    dependencies=[Depends(require_permission("ONBOARDING_CHECKLIST_UPDATE"))],
)
async def update_checklist_item(
    application_id: uuid.UUID,
    review_id: uuid.UUID,
    item_id: uuid.UUID,
    body: UpdateChecklistItemRequest,
    auth: CurrentAuth,
    service: Annotated[ReviewService, Depends(get_review_service)],
    review_repo=Depends(get_review_repo),
):
    review = await review_repo.get_by_id(review_id)
    if review is None or review.application_id != application_id:
        raise OnboardingError.for_code("ONBOARDING_APPLICATION_NOT_FOUND")
    item = await review_repo.get_checklist_item(item_id)
    if item is None or item.review_id != review_id:
        raise OnboardingError.for_code("ONBOARDING_APPLICATION_NOT_FOUND")

    await service.update_checklist_item(
        review,
        item,
        result=body.result,
        comments=body.comments,
        evidence_reference=body.evidence_reference,
        completed_by=auth.user.id,
    )
    return success({"itemId": str(item.id), "result": item.result})


@router.post(
    "/documents/{application_document_id}/review",
    summary="Review an application document",
    dependencies=[Depends(require_permission("ONBOARDING_DOCUMENT_REVIEW"))],
)
async def review_document(
    application_id: uuid.UUID,
    application_document_id: uuid.UUID,
    body: ReviewDocumentRequest,
    auth: CurrentAuth,
    service: Annotated[ReviewService, Depends(get_review_service)],
    application_repo=Depends(get_application_repo),
    document_repo=Depends(get_document_repo),
):
    application = await _load_application(application_id, application_repo)
    document = await document_repo.get_by_id(application_document_id)
    if document is None or document.application_id != application_id:
        raise OnboardingError.for_code("ONBOARDING_DOCUMENT_NOT_AVAILABLE")

    await service.review_document(
        application,
        document,
        decision=body.decision,
        comments=body.comments,
        verification_method=body.verification_method,
        verified_document_number=body.verified_document_number,
        verified_expiry_date=body.verified_expiry_date,
        reviewer_id=auth.user.id,
    )
    return success({"reviewStatus": document.review_status})


@router.post(
    "/reviews/{review_id}/complete",
    summary="Complete a review with a recommendation",
    dependencies=[Depends(require_permission("ONBOARDING_REVIEW_COMPLETE"))],
    responses={409: {"model": ErrorEnvelope, "description": "Mandatory checklist items unresolved"}},
)
async def complete_review(
    application_id: uuid.UUID,
    review_id: uuid.UUID,
    body: CompleteReviewRequest,
    auth: CurrentAuth,
    service: Annotated[ReviewService, Depends(get_review_service)],
    application_repo=Depends(get_application_repo),
    review_repo=Depends(get_review_repo),
):
    application = await _load_application(application_id, application_repo)
    review = await review_repo.get_by_id(review_id)
    if review is None or review.application_id != application_id:
        raise OnboardingError.for_code("ONBOARDING_APPLICATION_NOT_FOUND")

    await service.complete_review(
        application, review, recommendation=body.recommendation, comments=body.comments, completed_by=auth.user.id
    )
    return success({"status": review.status, "applicationStatus": application.status})
