"""Tests for application creation, sections, completeness, and submission
(spec sections 7, 8.1-8.6)."""

from __future__ import annotations

from tests.conftest import (
    ONBOARDING_APPLICANT_PERMISSIONS,
    auth_header,
    fill_doctor_application_sections,
    make_user_with_role,
    token_for,
    upload_doctor_documents,
)


async def _make_applicant(session_factory):
    user_id = await make_user_with_role(session_factory, "PATIENT")
    token = await token_for(user_id, ["PATIENT"], ONBOARDING_APPLICANT_PERMISSIONS)
    return user_id, auth_header(token)


async def test_create_application_success(client, session_factory):
    _, headers = await _make_applicant(session_factory)
    r = await client.post(
        "/api/v1/onboarding/me/application", json={"applicantType": "DOCTOR", "fullName": "Ana"}, headers=headers
    )
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["status"] == "DRAFT"
    assert data["applicationNumber"].startswith("ONB-DOC-")
    assert len(data["sections"]) == 5  # PERSONAL_INFORMATION, PROFESSIONAL_REGISTRATION, QUALIFICATIONS, DOCUMENTS, DECLARATIONS


async def test_duplicate_open_application_rejected(client, session_factory):
    _, headers = await _make_applicant(session_factory)
    await client.post("/api/v1/onboarding/me/application", json={"applicantType": "DOCTOR"}, headers=headers)
    r = await client.post("/api/v1/onboarding/me/application", json={"applicantType": "DOCTOR"}, headers=headers)
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "ONBOARDING_APPLICATION_ALREADY_EXISTS"


async def test_different_applicant_types_can_both_be_open(client, session_factory):
    _, headers = await _make_applicant(session_factory)
    r1 = await client.post("/api/v1/onboarding/me/application", json={"applicantType": "DOCTOR"}, headers=headers)
    r2 = await client.post("/api/v1/onboarding/me/application", json={"applicantType": "NUTRITIONIST"}, headers=headers)
    assert r1.status_code == 200
    assert r2.status_code == 200


async def test_get_current_application(client, session_factory):
    _, headers = await _make_applicant(session_factory)
    await client.post("/api/v1/onboarding/me/application", json={"applicantType": "DOCTOR"}, headers=headers)
    r = await client.get("/api/v1/onboarding/me/application", headers=headers)
    assert r.status_code == 200
    assert r.json()["data"]["applicantType"] == "DOCTOR"


async def test_get_requirements(client, session_factory):
    _, headers = await _make_applicant(session_factory)
    await client.post("/api/v1/onboarding/me/application", json={"applicantType": "DOCTOR"}, headers=headers)
    r = await client.get("/api/v1/onboarding/me/application/requirements", headers=headers)
    assert r.status_code == 200
    data = r.json()["data"]
    assert len(data["requiredSections"]) == 5
    doc_types = {d["documentType"] for d in data["requiredDocuments"]}
    assert "MEDICAL_COUNCIL_CERTIFICATE" in doc_types
    # MEDICAL_COUNCIL_CERTIFICATE is PDF-only per the spec's own example (8.2).
    mcc = next(d for d in data["requiredDocuments"] if d["documentType"] == "MEDICAL_COUNCIL_CERTIFICATE")
    assert mcc["allowedMimeTypes"] == ["application/pdf"]


async def test_update_section_computes_status(client, session_factory):
    _, headers = await _make_applicant(session_factory)
    await client.post("/api/v1/onboarding/me/application", json={"applicantType": "DOCTOR"}, headers=headers)

    r = await client.put(
        "/api/v1/onboarding/me/application/sections/PERSONAL_INFORMATION",
        json={"fullName": "Ana"},  # partial — missing dateOfBirth, nationalIdNumber, address
        headers=headers,
    )
    assert r.status_code == 200
    assert r.json()["data"]["status"] == "IN_PROGRESS"

    r = await client.put(
        "/api/v1/onboarding/me/application/sections/PERSONAL_INFORMATION",
        json={"fullName": "Ana", "dateOfBirth": "1990-01-01", "nationalIdNumber": "X", "address": "Y"},
        headers=headers,
    )
    assert r.status_code == 200
    assert r.json()["data"]["status"] == "COMPLETE"


async def test_update_invalid_section_code_rejected(client, session_factory):
    _, headers = await _make_applicant(session_factory)
    await client.post("/api/v1/onboarding/me/application", json={"applicantType": "DOCTOR"}, headers=headers)
    r = await client.put("/api/v1/onboarding/me/application/sections/NOT_A_REAL_SECTION", json={}, headers=headers)
    assert r.status_code == 409


async def test_documents_section_cannot_be_edited_directly(client, session_factory):
    _, headers = await _make_applicant(session_factory)
    await client.post("/api/v1/onboarding/me/application", json={"applicantType": "DOCTOR"}, headers=headers)
    r = await client.put("/api/v1/onboarding/me/application/sections/DOCUMENTS", json={}, headers=headers)
    assert r.status_code == 409


async def test_completeness_reports_missing_documents_and_sections(client, session_factory):
    _, headers = await _make_applicant(session_factory)
    await client.post("/api/v1/onboarding/me/application", json={"applicantType": "DOCTOR"}, headers=headers)
    r = await client.get("/api/v1/onboarding/me/application/completeness", headers=headers)
    data = r.json()["data"]
    assert data["complete"] is False
    assert data["completionPercentage"] == 0
    assert len(data["missingDocuments"]) > 0


async def test_submit_blocked_when_incomplete(client, session_factory):
    _, headers = await _make_applicant(session_factory)
    await client.post("/api/v1/onboarding/me/application", json={"applicantType": "DOCTOR"}, headers=headers)
    r = await client.post(
        "/api/v1/onboarding/me/application/submit",
        json={
            "declarationAccepted": True,
            "informationAccuracyConfirmed": True,
            "verificationConsentAccepted": True,
            "submissionVersion": 1,
        },
        headers=headers,
    )
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "ONBOARDING_APPLICATION_INCOMPLETE"
    assert "missingDocuments" in r.json()["error"]["details"]


async def test_submit_succeeds_when_complete_and_transitions_to_queued(client, session_factory):
    _, headers = await _make_applicant(session_factory)
    await client.post("/api/v1/onboarding/me/application", json={"applicantType": "DOCTOR"}, headers=headers)
    await fill_doctor_application_sections(client, headers)
    await upload_doctor_documents(client, headers)

    r = await client.get("/api/v1/onboarding/me/application/completeness", headers=headers)
    assert r.json()["data"]["complete"] is True

    r = await client.post(
        "/api/v1/onboarding/me/application/submit",
        json={
            "declarationAccepted": True,
            "informationAccuracyConfirmed": True,
            "verificationConsentAccepted": True,
            "submissionVersion": 1,
        },
        headers=headers,
    )
    assert r.status_code == 200
    assert r.json()["data"]["status"] == "QUEUED"


async def test_submit_version_conflict(client, session_factory):
    _, headers = await _make_applicant(session_factory)
    await client.post("/api/v1/onboarding/me/application", json={"applicantType": "DOCTOR"}, headers=headers)
    await fill_doctor_application_sections(client, headers)
    await upload_doctor_documents(client, headers)

    r = await client.post(
        "/api/v1/onboarding/me/application/submit",
        json={
            "declarationAccepted": True,
            "informationAccuracyConfirmed": True,
            "verificationConsentAccepted": True,
            "submissionVersion": 99,  # wrong version
        },
        headers=headers,
    )
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "ONBOARDING_APPLICATION_VERSION_CONFLICT"


async def test_submit_twice_rejected_as_already_submitted(client, session_factory):
    _, headers = await _make_applicant(session_factory)
    await client.post("/api/v1/onboarding/me/application", json={"applicantType": "DOCTOR"}, headers=headers)
    await fill_doctor_application_sections(client, headers)
    await upload_doctor_documents(client, headers)

    body = {
        "declarationAccepted": True,
        "informationAccuracyConfirmed": True,
        "verificationConsentAccepted": True,
        "submissionVersion": 1,
    }
    r1 = await client.post("/api/v1/onboarding/me/application/submit", json=body, headers=headers)
    assert r1.status_code == 200

    r2 = await client.post("/api/v1/onboarding/me/application/submit", json=body, headers=headers)
    assert r2.status_code == 409
    assert r2.json()["error"]["code"] == "ONBOARDING_APPLICATION_ALREADY_SUBMITTED"


async def test_withdraw_application(client, session_factory):
    _, headers = await _make_applicant(session_factory)
    await client.post("/api/v1/onboarding/me/application", json={"applicantType": "DOCTOR"}, headers=headers)
    r = await client.post(
        "/api/v1/onboarding/me/application/withdraw", json={"reason": "Changed my mind"}, headers=headers
    )
    assert r.status_code == 200
    assert r.json()["data"]["status"] == "WITHDRAWN"

    # A new application can now be created (the old one is no longer open).
    r2 = await client.post("/api/v1/onboarding/me/application", json={"applicantType": "DOCTOR"}, headers=headers)
    assert r2.status_code == 200
