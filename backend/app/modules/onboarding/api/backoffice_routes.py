"""Back-office routes: search, application detail, assignment, risk
flags, notes (spec sections 11, 12, 19, and the "Notes" field in 11.2)."""

from __future__ import annotations

import datetime
import math
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.core.envelope import ErrorEnvelope, success
from app.modules.identity.api.deps import require_permission
from app.modules.onboarding.api.deps import (
    CurrentAuth,
    get_application_repo,
    get_assignment_repo,
    get_assignment_service,
    get_decision_repo,
    get_risk_flag_repo,
    get_risk_flag_service,
)
from app.modules.onboarding.application.assignment_service import AssignmentService
from app.modules.onboarding.application.risk_flag_service import RiskFlagService
from app.modules.onboarding.application.schemas import (
    AddNoteRequest,
    ApplicationSearchResultOut,
    AssignApplicationRequest,
    NoteOut,
    PagedApplicationsOut,
    RaiseRiskFlagRequest,
    ReassignApplicationRequest,
    ReleaseApplicationRequest,
    ResolveRiskFlagRequest,
)
from app.modules.onboarding.domain.exceptions import OnboardingError
from app.modules.onboarding.domain.models import OnboardingApplicationNote

router = APIRouter(
    prefix="/back-office/onboarding/applications",
    tags=["Onboarding — Back Office"],
    responses={401: {"model": ErrorEnvelope}, 403: {"model": ErrorEnvelope}},
)


@router.get(
    "",
    summary="Search onboarding applications",
    dependencies=[Depends(require_permission("ONBOARDING_APPLICATION_SEARCH"))],
)
async def search_applications(
    application_repo=Depends(get_application_repo),
    applicant_type: Annotated[str | None, Query()] = None,
    status: Annotated[str | None, Query()] = None,
    application_number: Annotated[str | None, Query()] = None,
    assigned_reviewer_id: Annotated[uuid.UUID | None, Query()] = None,
    unassigned: Annotated[bool | None, Query()] = None,
    submitted_from: Annotated[datetime.date | None, Query()] = None,
    submitted_to: Annotated[datetime.date | None, Query()] = None,
    page: Annotated[int, Query(ge=0)] = 0,
    size: Annotated[int, Query(ge=1, le=100)] = 20,
):
    rows, total = await application_repo.search(
        applicant_type=applicant_type,
        status=status,
        application_number=application_number,
        assigned_reviewer_id=assigned_reviewer_id,
        unassigned=unassigned,
        submitted_from=submitted_from,
        submitted_to=submitted_to,
        page=page,
        size=size,
    )
    content = [
        ApplicationSearchResultOut(
            application_id=a.id,
            application_number=a.application_number,
            applicant_type=a.applicant_type,
            status=a.status,
            completion_percentage=a.completion_percentage,
            submitted_at=a.submitted_at,
            assigned_reviewer=a.current_reviewer_id,
            service_level_due_at=a.service_level_due_at,
        )
        for a in rows
    ]
    out = PagedApplicationsOut(
        content=content,
        page=page,
        size=size,
        total_elements=total,
        total_pages=max(1, math.ceil(total / size)) if total else 0,
    )
    return success(out.model_dump(by_alias=True, mode="json"))


@router.get(
    "/{application_id}",
    summary="Get application detail",
    dependencies=[Depends(require_permission("ONBOARDING_APPLICATION_READ"))],
)
async def get_application_detail(
    application_id: uuid.UUID,
    application_repo=Depends(get_application_repo),
    assignment_repo=Depends(get_assignment_repo),
    decision_repo=Depends(get_decision_repo),
    risk_flag_repo=Depends(get_risk_flag_repo),
):
    application = await application_repo.get_by_id(application_id)
    if application is None:
        raise OnboardingError.for_code("ONBOARDING_APPLICATION_NOT_FOUND")

    sections = await application_repo.list_sections(application_id)
    parties = await application_repo.list_parties(application_id)
    status_history = await application_repo.list_status_history(application_id)
    notes = await application_repo.list_notes(application_id)
    assignments = await assignment_repo.list_active(application_id)
    decisions = await decision_repo.list_for_application(application_id)
    risk_flags = await risk_flag_repo.list_for_application(application_id)

    result = {
        "application": {
            "id": str(application.id),
            "applicationNumber": application.application_number,
            "applicantType": application.applicant_type,
            "purpose": application.application_purpose,
            "status": application.status,
            "completionPercentage": application.completion_percentage,
            "submittedAt": application.submitted_at.isoformat() if application.submitted_at else None,
            "currentStep": None,
            "sections": [{"code": s.section_code, "status": s.status} for s in sections],
        },
        "parties": [
            {
                "id": str(p.id),
                "partyType": p.party_type,
                "fullName": p.full_name,
                "organisationName": p.organisation_name,
            }
            for p in parties
        ],
        "assignments": [
            {
                "id": str(a.id),
                "reviewerId": str(a.reviewer_id),
                "assignmentType": a.assignment_type,
                "assignedAt": a.assigned_at.isoformat(),
                "active": a.active,
            }
            for a in assignments
        ],
        "statusHistory": [
            {
                "previousStatus": h.previous_status,
                "newStatus": h.new_status,
                "changedBy": str(h.changed_by) if h.changed_by else None,
                "reasonCode": h.reason_code,
                "comments": h.comments,
                "createdAt": h.created_at.isoformat(),
            }
            for h in status_history
        ],
        "decisions": [
            {
                "id": str(d.id),
                "decisionType": d.decision_type,
                "decisionBy": str(d.decision_by),
                "decisionComments": d.decision_comments,
                "reasonCode": d.reason_code,
                "approvalValidUntil": d.approval_valid_until.isoformat() if d.approval_valid_until else None,
                "conditions": d.conditions,
                "createdAt": d.created_at.isoformat(),
            }
            for d in decisions
        ],
        "riskFlags": [
            {
                "id": str(r.id),
                "flagCode": r.flag_code,
                "riskLevel": r.risk_level,
                "description": r.description,
                "status": r.status,
                "raisedAt": r.raised_at.isoformat(),
                "resolvedAt": r.resolved_at.isoformat() if r.resolved_at else None,
            }
            for r in risk_flags
        ],
        "notes": [
            NoteOut(id=n.id, author_id=n.author_id, content=n.content, created_at=n.created_at).model_dump(
                by_alias=True, mode="json"
            )
            for n in notes
        ],
    }
    return success(result)


@router.post(
    "/{application_id}/assign",
    summary="Assign an application to a reviewer",
    dependencies=[Depends(require_permission("ONBOARDING_APPLICATION_ASSIGN"))],
)
async def assign_application(
    application_id: uuid.UUID,
    body: AssignApplicationRequest,
    auth: CurrentAuth,
    service: Annotated[AssignmentService, Depends(get_assignment_service)],
    application_repo=Depends(get_application_repo),
):
    application = await application_repo.get_by_id(application_id)
    if application is None:
        raise OnboardingError.for_code("ONBOARDING_APPLICATION_NOT_FOUND")

    assignment = await service.assign(
        application,
        reviewer_id=body.reviewer_id,
        assignment_type=body.assignment_type,
        assigned_by=auth.user.id,
        reason=body.reason,
    )
    return success({"assignmentId": str(assignment.id)})


@router.post(
    "/{application_id}/claim",
    summary="Claim an unassigned application",
    dependencies=[Depends(require_permission("ONBOARDING_APPLICATION_CLAIM"))],
)
async def claim_application(
    application_id: uuid.UUID,
    auth: CurrentAuth,
    service: Annotated[AssignmentService, Depends(get_assignment_service)],
):
    assignment = await service.claim(application_id, reviewer_id=auth.user.id)
    return success({"assignmentId": str(assignment.id)})


@router.post(
    "/{application_id}/reassign",
    summary="Reassign an application to a different reviewer",
    dependencies=[Depends(require_permission("ONBOARDING_APPLICATION_REASSIGN"))],
)
async def reassign_application(
    application_id: uuid.UUID,
    body: ReassignApplicationRequest,
    auth: CurrentAuth,
    service: Annotated[AssignmentService, Depends(get_assignment_service)],
    application_repo=Depends(get_application_repo),
):
    application = await application_repo.get_by_id(application_id)
    if application is None:
        raise OnboardingError.for_code("ONBOARDING_APPLICATION_NOT_FOUND")

    assignment = await service.reassign(
        application, new_reviewer_id=body.new_reviewer_id, reason=body.reason, reassigned_by=auth.user.id
    )
    return success({"assignmentId": str(assignment.id)})


@router.post(
    "/{application_id}/release",
    summary="Release an application back to the unassigned queue",
    dependencies=[Depends(require_permission("ONBOARDING_APPLICATION_ASSIGN"))],
)
async def release_application(
    application_id: uuid.UUID,
    body: ReleaseApplicationRequest,
    auth: CurrentAuth,
    service: Annotated[AssignmentService, Depends(get_assignment_service)],
    application_repo=Depends(get_application_repo),
):
    application = await application_repo.get_by_id(application_id)
    if application is None:
        raise OnboardingError.for_code("ONBOARDING_APPLICATION_NOT_FOUND")

    await service.release(application, reason=body.reason, released_by=auth.user.id)
    return success({"released": True})


# --- Risk flags (spec 19) -------------------------------------------------------


@router.post(
    "/{application_id}/risk-flags",
    summary="Raise a risk flag",
    dependencies=[Depends(require_permission("ONBOARDING_RISK_FLAG_MANAGE"))],
)
async def raise_risk_flag(
    application_id: uuid.UUID,
    body: RaiseRiskFlagRequest,
    auth: CurrentAuth,
    service: Annotated[RiskFlagService, Depends(get_risk_flag_service)],
    application_repo=Depends(get_application_repo),
):
    application = await application_repo.get_by_id(application_id)
    if application is None:
        raise OnboardingError.for_code("ONBOARDING_APPLICATION_NOT_FOUND")

    flag = await service.raise_flag(
        application,
        flag_code=body.flag_code,
        risk_level=body.risk_level,
        description=body.description,
        raised_by=auth.user.id,
    )
    return success({"riskFlagId": str(flag.id)})


@router.post(
    "/{application_id}/risk-flags/{flag_id}/resolve",
    summary="Resolve a risk flag",
    dependencies=[Depends(require_permission("ONBOARDING_RISK_FLAG_MANAGE"))],
)
async def resolve_risk_flag(
    application_id: uuid.UUID,
    flag_id: uuid.UUID,
    body: ResolveRiskFlagRequest,
    service: Annotated[RiskFlagService, Depends(get_risk_flag_service)],
    application_repo=Depends(get_application_repo),
    risk_flag_repo=Depends(get_risk_flag_repo),
):
    application = await application_repo.get_by_id(application_id)
    if application is None:
        raise OnboardingError.for_code("ONBOARDING_APPLICATION_NOT_FOUND")
    flag = await risk_flag_repo.get_by_id(flag_id)
    if flag is None or flag.application_id != application_id:
        raise OnboardingError.for_code("ONBOARDING_RISK_FLAG_NOT_FOUND")

    await service.resolve_flag(
        application,
        flag,
        status=body.status,
        resolution_comments=body.resolution_comments,
        evidence_reference=body.evidence_reference,
    )
    return success({"status": flag.status})


# --- Notes -------------------------------------------------------------------------


@router.post(
    "/{application_id}/notes",
    summary="Add an internal note to an application",
    dependencies=[Depends(require_permission("ONBOARDING_APPLICATION_READ"))],
)
async def add_note(
    application_id: uuid.UUID,
    body: AddNoteRequest,
    auth: CurrentAuth,
    application_repo=Depends(get_application_repo),
):
    application = await application_repo.get_by_id(application_id)
    if application is None:
        raise OnboardingError.for_code("ONBOARDING_APPLICATION_NOT_FOUND")

    note = OnboardingApplicationNote(application_id=application_id, author_id=auth.user.id, content=body.content)
    await application_repo.add_note(note)
    return success({"noteId": str(note.id)})
