"""Tests for information requests (spec 15) and document upload
validation edge cases (spec 9)."""

from __future__ import annotations

from tests.conftest import (
    ONBOARDING_APPLICANT_PERMISSIONS,
    ONBOARDING_REVIEWER_PERMISSIONS,
    auth_header,
    fill_doctor_application_sections,
    make_user_with_role,
    token_for,
    upload_doctor_documents,
)


async def _under_review_application(client, session_factory):
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

    reviewer_id = await make_user_with_role(session_factory, "BACK_OFFICE_REVIEWER")
    reviewer_token = await token_for(reviewer_id, ["BACK_OFFICE_REVIEWER"], ONBOARDING_REVIEWER_PERMISSIONS)
    reviewer_headers = auth_header(reviewer_token)
    await client.post(f"/api/v1/back-office/onboarding/applications/{application_id}/claim", headers=reviewer_headers)
    await client.post(
        f"/api/v1/back-office/onboarding/applications/{application_id}/reviews/start",
        json={"reviewType": "INITIAL_REVIEW"},
        headers=reviewer_headers,
    )
    return application_id, applicant_headers, reviewer_headers


async def test_create_information_request_moves_application_to_additional_info_required(client, session_factory):
    application_id, applicant_headers, reviewer_headers = await _under_review_application(client, session_factory)

    r = await client.post(
        f"/api/v1/back-office/onboarding/applications/{application_id}/information-requests",
        json={
            "reasonCode": "DOCUMENT_UNREADABLE",
            "message": "Please upload a clearer copy of the medical council certificate.",
            "items": [
                {
                    "itemType": "DOCUMENT",
                    "documentType": "MEDICAL_COUNCIL_CERTIFICATE",
                    "instruction": "Upload a complete colour copy.",
                }
            ],
        },
        headers=reviewer_headers,
    )
    assert r.status_code == 200

    detail = await client.get(f"/api/v1/back-office/onboarding/applications/{application_id}", headers=reviewer_headers)
    assert detail.json()["data"]["application"]["status"] == "ADDITIONAL_INFORMATION_REQUIRED"


async def test_applicant_sees_information_request(client, session_factory):
    application_id, applicant_headers, reviewer_headers = await _under_review_application(client, session_factory)
    await client.post(
        f"/api/v1/back-office/onboarding/applications/{application_id}/information-requests",
        json={"reasonCode": "DOCUMENT_UNREADABLE", "message": "Please clarify.", "items": []},
        headers=reviewer_headers,
    )

    r = await client.get("/api/v1/onboarding/me/application/information-requests", headers=applicant_headers)
    assert r.status_code == 200
    assert len(r.json()["data"]) == 1
    assert r.json()["data"][0]["status"] == "OPEN"


async def test_respond_and_resubmit_flow(client, session_factory):
    application_id, applicant_headers, reviewer_headers = await _under_review_application(client, session_factory)
    r = await client.post(
        f"/api/v1/back-office/onboarding/applications/{application_id}/information-requests",
        json={
            "reasonCode": "DOCUMENT_UNREADABLE",
            "message": "Please clarify your declaration.",
            "items": [{"itemType": "DECLARATION", "instruction": "Confirm accuracy again."}],
        },
        headers=reviewer_headers,
    )
    request_id = r.json()["data"]["requestId"]

    r2 = await client.post(
        f"/api/v1/onboarding/me/application/information-requests/{request_id}/respond",
        json={"message": "Confirmed, all information is accurate."},
        headers=applicant_headers,
    )
    assert r2.status_code == 200
    assert r2.json()["data"]["status"] == "SATISFIED"  # only item addressed -> fully satisfied, not just responded

    r3 = await client.post(
        "/api/v1/onboarding/me/application/resubmit",
        json={"informationRequestId": request_id, "informationAccuracyConfirmed": True},
        headers=applicant_headers,
    )
    assert r3.status_code == 200
    assert r3.json()["data"]["status"] == "RESUBMITTED"


# --- Document validation edge cases (spec 9, 29.3) --------------------------------


async def _applicant_with_application(client, session_factory):
    applicant_id = await make_user_with_role(session_factory, "PATIENT")
    token = await token_for(applicant_id, ["PATIENT"], ONBOARDING_APPLICANT_PERMISSIONS)
    headers = auth_header(token)
    await client.post("/api/v1/onboarding/me/application", json={"applicantType": "DOCTOR"}, headers=headers)
    return headers


async def test_upload_request_rejects_disallowed_document_type(client, session_factory):
    headers = await _applicant_with_application(client, session_factory)
    r = await client.post(
        "/api/v1/onboarding/me/application/documents/upload-request",
        json={"documentType": "NOT_A_REAL_DOCUMENT_TYPE", "fileName": "x.pdf", "mimeType": "application/pdf", "fileSize": 1000},
        headers=headers,
    )
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "ONBOARDING_DOCUMENT_TYPE_NOT_ALLOWED"


async def test_upload_request_rejects_disallowed_mime_type(client, session_factory):
    headers = await _applicant_with_application(client, session_factory)
    r = await client.post(
        "/api/v1/onboarding/me/application/documents/upload-request",
        json={"documentType": "MEDICAL_COUNCIL_CERTIFICATE", "fileName": "x.png", "mimeType": "image/png", "fileSize": 1000},
        headers=headers,
    )
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "ONBOARDING_DOCUMENT_MIME_TYPE_NOT_ALLOWED"


async def test_upload_request_rejects_oversized_file(client, session_factory):
    headers = await _applicant_with_application(client, session_factory)
    r = await client.post(
        "/api/v1/onboarding/me/application/documents/upload-request",
        json={
            "documentType": "NATIONAL_ID",
            "fileName": "x.pdf",
            "mimeType": "application/pdf",
            "fileSize": 999_999_999,
        },
        headers=headers,
    )
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "ONBOARDING_DOCUMENT_FILE_TOO_LARGE"


async def test_replace_document_supersedes_old_version(client, session_factory):
    headers = await _applicant_with_application(client, session_factory)
    r = await client.post(
        "/api/v1/onboarding/me/application/documents/upload-request",
        json={"documentType": "NATIONAL_ID", "fileName": "id.pdf", "mimeType": "application/pdf", "fileSize": 1000},
        headers=headers,
    )
    old_id = r.json()["data"]["applicationDocumentId"]
    await client.post(f"/api/v1/onboarding/me/application/documents/{old_id}/confirm", json={"checksum": "a"}, headers=headers)

    r2 = await client.post(
        f"/api/v1/onboarding/me/application/documents/{old_id}/replace",
        json={"documentType": "NATIONAL_ID", "fileName": "id-v2.pdf", "mimeType": "application/pdf", "fileSize": 1200},
        headers=headers,
    )
    assert r2.status_code == 200
    new_id = r2.json()["data"]["applicationDocumentId"]
    assert new_id != old_id

    docs = await client.get("/api/v1/onboarding/me/application/documents", headers=headers)
    current_ids = {d["id"] for d in docs.json()["data"]}
    assert new_id in current_ids
    assert old_id not in current_ids  # superseded, no longer "current"
