"""Tests for verification checks (spec 14), decisions and maker-checker
(spec 16), and suspension (spec 17)."""

from __future__ import annotations

from sqlalchemy import select

from app.modules.identity.domain.models import Role, UserRole
from tests.conftest import (
    ONBOARDING_APPLICANT_PERMISSIONS,
    ONBOARDING_APPROVER_PERMISSIONS,
    ONBOARDING_REVIEWER_PERMISSIONS,
    auth_header,
    fill_doctor_application_sections,
    make_user_with_role,
    token_for,
    upload_doctor_documents,
)


async def _application_pending_approval(client, session_factory, *, same_reviewer_and_approver=False):
    """Builds an application all the way to PENDING_APPROVAL. Returns
    (application_id, applicant_id, applicant_headers, reviewer_headers,
    approver_headers).
    """
    applicant_id = await make_user_with_role(session_factory, "PATIENT")
    applicant_token = await token_for(applicant_id, ["PATIENT"], ONBOARDING_APPLICANT_PERMISSIONS)
    applicant_headers = auth_header(applicant_token)

    r = await client.post("/api/v1/onboarding/me/application", json={"applicantType": "DOCTOR"}, headers=applicant_headers)
    application_id = r.json()["data"]["id"]
    await fill_doctor_application_sections(client, applicant_headers)
    await upload_doctor_documents(client, applicant_headers)
    await client.post(
        "/api/v1/onboarding/me/application/submit",
        json={
            "declarationAccepted": True,
            "informationAccuracyConfirmed": True,
            "verificationConsentAccepted": True,
            "submissionVersion": 1,
        },
        headers=applicant_headers,
    )

    if same_reviewer_and_approver:
        approver_id = await make_user_with_role(session_factory, "BACK_OFFICE_APPROVER")
        approver_token = await token_for(approver_id, ["BACK_OFFICE_APPROVER"], ONBOARDING_APPROVER_PERMISSIONS)
        approver_headers = auth_header(approver_token)
        reviewer_headers = approver_headers
    else:
        reviewer_id = await make_user_with_role(session_factory, "BACK_OFFICE_REVIEWER")
        reviewer_token = await token_for(reviewer_id, ["BACK_OFFICE_REVIEWER"], ONBOARDING_REVIEWER_PERMISSIONS)
        reviewer_headers = auth_header(reviewer_token)

        approver_id = await make_user_with_role(session_factory, "BACK_OFFICE_APPROVER")
        approver_token = await token_for(approver_id, ["BACK_OFFICE_APPROVER"], ONBOARDING_APPROVER_PERMISSIONS)
        approver_headers = auth_header(approver_token)

    await client.post(f"/api/v1/back-office/onboarding/applications/{application_id}/claim", headers=reviewer_headers)
    r = await client.post(
        f"/api/v1/back-office/onboarding/applications/{application_id}/reviews/start",
        json={"reviewType": "INITIAL_REVIEW"},
        headers=reviewer_headers,
    )
    review_id = r.json()["data"]["reviewId"]

    checklist = await client.get(
        f"/api/v1/back-office/onboarding/applications/{application_id}/reviews/{review_id}", headers=reviewer_headers
    )
    for item in checklist.json()["data"]["checklistItems"]:
        await client.patch(
            f"/api/v1/back-office/onboarding/applications/{application_id}/reviews/{review_id}/checklist-items/{item['id']}",
            json={"result": "PASS"},
            headers=reviewer_headers,
        )

    docs = await client.get("/api/v1/onboarding/me/application/documents", headers=applicant_headers)
    for doc in docs.json()["data"]:
        await client.post(
            f"/api/v1/back-office/onboarding/applications/{application_id}/documents/{doc['id']}/review",
            json={"decision": "ACCEPTED"},
            headers=reviewer_headers,
        )

    await client.post(
        f"/api/v1/back-office/onboarding/applications/{application_id}/reviews/{review_id}/complete",
        json={"recommendation": "APPROVE"},
        headers=reviewer_headers,
    )

    return application_id, applicant_id, applicant_headers, reviewer_headers, approver_headers


async def test_approve_application(client, session_factory):
    application_id, _, _, _, approver_headers = await _application_pending_approval(client, session_factory)

    r = await client.post(
        f"/api/v1/back-office/onboarding/applications/{application_id}/approve",
        json={"decisionComments": "All good"},
        headers=approver_headers,
    )
    assert r.status_code == 200
    assert r.json()["data"]["status"] == "APPROVED"


async def test_maker_checker_blocks_reviewer_from_approving(client, session_factory):
    application_id, _, _, reviewer_headers, _ = await _application_pending_approval(client, session_factory)

    r = await client.post(
        f"/api/v1/back-office/onboarding/applications/{application_id}/approve", json={}, headers=reviewer_headers
    )
    # BACK_OFFICE_REVIEWER doesn't have ONBOARDING_APPLICATION_APPROVE at
    # all, so this is blocked at the permission layer.
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "PERMISSION_DENIED"


async def test_maker_checker_blocks_same_person_reviewing_and_approving(client, session_factory):
    application_id, _, _, _, approver_headers = await _application_pending_approval(
        client, session_factory, same_reviewer_and_approver=True
    )

    r = await client.post(
        f"/api/v1/back-office/onboarding/applications/{application_id}/approve", json={}, headers=approver_headers
    )
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "ONBOARDING_MAKER_CHECKER_VIOLATION"


async def test_approval_role_transition_happens_via_outbox(client, session_factory):
    application_id, applicant_id, _, _, approver_headers = await _application_pending_approval(client, session_factory)
    await client.post(
        f"/api/v1/back-office/onboarding/applications/{application_id}/approve", json={}, headers=approver_headers
    )

    from app.modules.onboarding.application.outbox_dispatcher import dispatch_once

    for _ in range(10):
        if await dispatch_once() == 0:
            break

    async with session_factory() as s:
        roles = (
            await s.execute(
                select(Role.code)
                .join(UserRole, UserRole.role_id == Role.id)
                .where(UserRole.user_id == applicant_id, UserRole.active.is_(True))
            )
        ).scalars().all()
        assert "DOCTOR" in roles


async def test_approval_triggers_provider_activation(client, session_factory):
    application_id, applicant_id, _, _, approver_headers = await _application_pending_approval(client, session_factory)
    r = await client.post(
        f"/api/v1/back-office/onboarding/applications/{application_id}/approve", json={}, headers=approver_headers
    )
    assert r.status_code == 200

    from app.modules.onboarding.application.outbox_dispatcher import dispatch_once
    from app.shared.provider.port import get_provider_adapter

    for _ in range(10):
        if await dispatch_once() == 0:
            break

    adapter = get_provider_adapter()
    activation_calls = [c for c in adapter.calls if c.action == "ACTIVATE"]
    assert len(activation_calls) >= 1


async def test_reject_application_requires_comments(client, session_factory):
    application_id, _, _, _, approver_headers = await _application_pending_approval(client, session_factory)

    r = await client.post(
        f"/api/v1/back-office/onboarding/applications/{application_id}/reject",
        json={"reasonCode": "INVALID_PROFESSIONAL_REGISTRATION", "decisionComments": ""},
        headers=approver_headers,
    )
    assert r.status_code == 422


async def test_reject_application_success(client, session_factory):
    application_id, _, _, _, approver_headers = await _application_pending_approval(client, session_factory)

    r = await client.post(
        f"/api/v1/back-office/onboarding/applications/{application_id}/reject",
        json={
            "reasonCode": "INVALID_PROFESSIONAL_REGISTRATION",
            "decisionComments": "Could not verify registration number.",
            "allowNewApplication": True,
            "coolingOffPeriodDays": 30,
        },
        headers=approver_headers,
    )
    assert r.status_code == 200
    assert r.json()["data"]["status"] == "REJECTED"


async def test_cannot_approve_twice(client, session_factory):
    application_id, _, _, _, approver_headers = await _application_pending_approval(client, session_factory)
    r1 = await client.post(
        f"/api/v1/back-office/onboarding/applications/{application_id}/approve", json={}, headers=approver_headers
    )
    assert r1.status_code == 200

    r2 = await client.post(
        f"/api/v1/back-office/onboarding/applications/{application_id}/approve", json={}, headers=approver_headers
    )
    assert r2.status_code in {403, 409}  # PENDING_APPROVAL precondition no longer holds


async def test_suspend_approved_application(client, session_factory):
    application_id, _, _, _, approver_headers = await _application_pending_approval(client, session_factory)
    await client.post(f"/api/v1/back-office/onboarding/applications/{application_id}/approve", json={}, headers=approver_headers)

    r = await client.post(
        f"/api/v1/back-office/onboarding/applications/{application_id}/suspend",
        json={"reasonCode": "PROFESSIONAL_LICENCE_EXPIRED", "comments": "Licence expired."},
        headers=approver_headers,
    )
    assert r.status_code == 200
    assert r.json()["data"]["status"] == "SUSPENDED"


async def test_suspend_non_approved_application_rejected(client, session_factory):
    application_id, _, _, _, approver_headers = await _application_pending_approval(client, session_factory)
    # Never approved — still PENDING_APPROVAL.
    r = await client.post(
        f"/api/v1/back-office/onboarding/applications/{application_id}/suspend",
        json={"reasonCode": "PROFESSIONAL_LICENCE_EXPIRED"},
        headers=approver_headers,
    )
    assert r.status_code == 409


async def test_verification_check_manual_provider(client, session_factory):
    application_id, _, _, reviewer_headers, _ = await _application_pending_approval(client, session_factory)

    r = await client.post(
        f"/api/v1/back-office/onboarding/applications/{application_id}/verification-checks",
        json={"checkType": "PROFESSIONAL_REGISTRY", "provider": "MANUAL", "subjectReference": "OM-2026-001"},
        headers=reviewer_headers,
    )
    assert r.status_code == 200
    check_id = r.json()["data"]["id"]
    assert r.json()["data"]["status"] == "PENDING"

    r2 = await client.post(
        f"/api/v1/back-office/onboarding/applications/{application_id}/verification-checks/{check_id}/complete",
        json={"result": "MATCH", "externalReference": "REG-123", "verifiedData": {"status": "ACTIVE"}},
        headers=reviewer_headers,
    )
    assert r2.status_code == 200
    assert r2.json()["data"]["result"] == "MATCH"


async def test_verification_check_automatic_provider_completes_immediately(client, session_factory):
    application_id, _, _, reviewer_headers, _ = await _application_pending_approval(client, session_factory)

    r = await client.post(
        f"/api/v1/back-office/onboarding/applications/{application_id}/verification-checks",
        json={"checkType": "COMPANY_REGISTRY", "provider": "MOCK_REGISTRY", "subjectReference": "COMPANY-123"},
        headers=reviewer_headers,
    )
    assert r.status_code == 200
    # Automatic (non-MANUAL) providers attempt an immediate result.
    assert r.json()["data"]["status"] == "COMPLETED"
    assert r.json()["data"]["result"] == "MATCH"
