"""Tests for assignment (spec 12, concurrency in 28) and review lifecycle
(spec 13)."""

from __future__ import annotations

import asyncio

from tests.conftest import (
    ONBOARDING_APPLICANT_PERMISSIONS,
    ONBOARDING_REVIEWER_PERMISSIONS,
    auth_header,
    fill_doctor_application_sections,
    make_user_with_role,
    token_for,
    upload_doctor_documents,
)


async def _submitted_application(client, session_factory):
    applicant_id = await make_user_with_role(session_factory, "PATIENT")
    applicant_token = await token_for(applicant_id, ["PATIENT"], ONBOARDING_APPLICANT_PERMISSIONS)
    headers = auth_header(applicant_token)

    r = await client.post("/api/v1/onboarding/me/application", json={"applicantType": "DOCTOR"}, headers=headers)
    application_id = r.json()["data"]["id"]
    await fill_doctor_application_sections(client, headers)
    await upload_doctor_documents(client, headers)
    await client.post(
        "/api/v1/onboarding/me/application/submit",
        json={
            "declarationAccepted": True,
            "informationAccuracyConfirmed": True,
            "verificationConsentAccepted": True,
            "submissionVersion": 1,
        },
        headers=headers,
    )
    return application_id, applicant_id, headers


async def _reviewer(session_factory):
    reviewer_id = await make_user_with_role(session_factory, "BACK_OFFICE_REVIEWER")
    token = await token_for(reviewer_id, ["BACK_OFFICE_REVIEWER"], ONBOARDING_REVIEWER_PERMISSIONS)
    return reviewer_id, auth_header(token)


async def test_search_finds_queued_application(client, session_factory):
    application_id, _, _ = await _submitted_application(client, session_factory)
    _, reviewer_headers = await _reviewer(session_factory)

    r = await client.get(
        "/api/v1/back-office/onboarding/applications", params={"status": "QUEUED"}, headers=reviewer_headers
    )
    assert r.status_code == 200
    ids = [a["applicationId"] for a in r.json()["data"]["content"]]
    assert application_id in ids


async def test_claim_application(client, session_factory):
    application_id, _, _ = await _submitted_application(client, session_factory)
    reviewer_id, reviewer_headers = await _reviewer(session_factory)

    r = await client.post(f"/api/v1/back-office/onboarding/applications/{application_id}/claim", headers=reviewer_headers)
    assert r.status_code == 200


async def test_second_claim_of_same_application_rejected(client, session_factory):
    application_id, _, _ = await _submitted_application(client, session_factory)
    _, reviewer1_headers = await _reviewer(session_factory)
    _, reviewer2_headers = await _reviewer(session_factory)

    r1 = await client.post(f"/api/v1/back-office/onboarding/applications/{application_id}/claim", headers=reviewer1_headers)
    assert r1.status_code == 200

    r2 = await client.post(f"/api/v1/back-office/onboarding/applications/{application_id}/claim", headers=reviewer2_headers)
    assert r2.status_code == 409
    assert r2.json()["error"]["code"] == "ONBOARDING_APPLICATION_ALREADY_ASSIGNED"


async def test_concurrent_claims_only_one_succeeds(client, session_factory):
    """spec 28: 'Simulate two reviewers claiming the same application ...
    Only one claim succeeds. The other receives a conflict response.'
    """
    application_id, _, _ = await _submitted_application(client, session_factory)
    _, reviewer1_headers = await _reviewer(session_factory)
    _, reviewer2_headers = await _reviewer(session_factory)

    results = await asyncio.gather(
        client.post(f"/api/v1/back-office/onboarding/applications/{application_id}/claim", headers=reviewer1_headers),
        client.post(f"/api/v1/back-office/onboarding/applications/{application_id}/claim", headers=reviewer2_headers),
        return_exceptions=True,
    )
    status_codes = sorted(r.status_code for r in results if not isinstance(r, Exception))
    assert status_codes == [200, 409]


async def test_start_review_requires_assignment(client, session_factory):
    application_id, _, _ = await _submitted_application(client, session_factory)
    _, reviewer_headers = await _reviewer(session_factory)

    r = await client.post(
        f"/api/v1/back-office/onboarding/applications/{application_id}/reviews/start",
        json={"reviewType": "INITIAL_REVIEW"},
        headers=reviewer_headers,
    )
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "ONBOARDING_APPLICATION_NOT_ASSIGNED"


async def test_start_review_moves_application_to_under_review(client, session_factory):
    application_id, _, _ = await _submitted_application(client, session_factory)
    _, reviewer_headers = await _reviewer(session_factory)

    await client.post(f"/api/v1/back-office/onboarding/applications/{application_id}/claim", headers=reviewer_headers)
    r = await client.post(
        f"/api/v1/back-office/onboarding/applications/{application_id}/reviews/start",
        json={"reviewType": "INITIAL_REVIEW"},
        headers=reviewer_headers,
    )
    assert r.status_code == 200
    review_id = r.json()["data"]["reviewId"]

    detail = await client.get(f"/api/v1/back-office/onboarding/applications/{application_id}", headers=reviewer_headers)
    assert detail.json()["data"]["application"]["status"] == "UNDER_REVIEW"

    checklist = await client.get(
        f"/api/v1/back-office/onboarding/applications/{application_id}/reviews/{review_id}", headers=reviewer_headers
    )
    assert len(checklist.json()["data"]["checklistItems"]) > 0


async def test_complete_review_blocked_by_unresolved_mandatory_checklist_items(client, session_factory):
    application_id, _, _ = await _submitted_application(client, session_factory)
    _, reviewer_headers = await _reviewer(session_factory)
    await client.post(f"/api/v1/back-office/onboarding/applications/{application_id}/claim", headers=reviewer_headers)
    r = await client.post(
        f"/api/v1/back-office/onboarding/applications/{application_id}/reviews/start",
        json={"reviewType": "INITIAL_REVIEW"},
        headers=reviewer_headers,
    )
    review_id = r.json()["data"]["reviewId"]

    r = await client.post(
        f"/api/v1/back-office/onboarding/applications/{application_id}/reviews/{review_id}/complete",
        json={"recommendation": "APPROVE"},
        headers=reviewer_headers,
    )
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "ONBOARDING_CHECKLIST_INCOMPLETE"


async def test_complete_review_with_all_checklist_items_passed(client, session_factory):
    application_id, _, _ = await _submitted_application(client, session_factory)
    _, reviewer_headers = await _reviewer(session_factory)
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
        r = await client.patch(
            f"/api/v1/back-office/onboarding/applications/{application_id}/reviews/{review_id}/checklist-items/{item['id']}",
            json={"result": "PASS"},
            headers=reviewer_headers,
        )
        assert r.status_code == 200

    r = await client.post(
        f"/api/v1/back-office/onboarding/applications/{application_id}/reviews/{review_id}/complete",
        json={"recommendation": "APPROVE"},
        headers=reviewer_headers,
    )
    assert r.status_code == 200
    assert r.json()["data"]["applicationStatus"] == "PENDING_APPROVAL"


async def test_document_review_accept(client, session_factory):
    application_id, _, applicant_headers = await _submitted_application(client, session_factory)
    _, reviewer_headers = await _reviewer(session_factory)
    await client.post(f"/api/v1/back-office/onboarding/applications/{application_id}/claim", headers=reviewer_headers)

    docs = await client.get("/api/v1/onboarding/me/application/documents", headers=applicant_headers)
    doc_id = docs.json()["data"][0]["id"]

    r = await client.post(
        f"/api/v1/back-office/onboarding/applications/{application_id}/documents/{doc_id}/review",
        json={"decision": "ACCEPTED", "comments": "Looks valid"},
        headers=reviewer_headers,
    )
    assert r.status_code == 200
    assert r.json()["data"]["reviewStatus"] == "ACCEPTED"


async def test_document_rejection_requires_comments(client, session_factory):
    application_id, _, applicant_headers = await _submitted_application(client, session_factory)
    _, reviewer_headers = await _reviewer(session_factory)
    await client.post(f"/api/v1/back-office/onboarding/applications/{application_id}/claim", headers=reviewer_headers)

    docs = await client.get("/api/v1/onboarding/me/application/documents", headers=applicant_headers)
    doc_id = docs.json()["data"][0]["id"]

    r = await client.post(
        f"/api/v1/back-office/onboarding/applications/{application_id}/documents/{doc_id}/review",
        json={"decision": "REJECTED"},
        headers=reviewer_headers,
    )
    assert r.status_code == 422
