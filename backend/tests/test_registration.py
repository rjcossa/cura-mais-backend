"""Tests for POST /auth/register/patient and /auth/register/doctor
(spec section 25.1)."""

from __future__ import annotations

import pytest

from tests.conftest import patient_payload


async def test_register_patient_success(client):
    r = await client.post("/api/v1/auth/register/patient", json=patient_payload())
    assert r.status_code == 201
    body = r.json()
    assert body["success"] is True
    assert body["data"]["accountStatus"] == "PENDING_VERIFICATION"
    assert body["data"]["emailVerificationRequired"] is True
    assert body["data"]["mobileVerificationRequired"] is True


async def test_register_doctor_applicant_success(client):
    payload = {
        "email": "doctor@example.com",
        "password": "SecurePassword@123",
        "mobileNumber": "+258842345678",
        "firstName": "Paulo",
        "lastName": "Mucavele",
        "termsAccepted": True,
        "privacyPolicyAccepted": True,
        "professionalDataConsentAccepted": True,
    }
    r = await client.post("/api/v1/auth/register/doctor", json=payload)
    assert r.status_code == 201

    # A doctor applicant must not be able to log in as an approved doctor;
    # confirm the role landed correctly via the profile endpoint.
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": payload["email"], "password": payload["password"], "device": {}},
    )
    token = login.json()["data"]["accessToken"]
    profile = await client.get("/api/v1/users/me", headers={"Authorization": f"Bearer {token}"})
    assert profile.json()["data"]["roles"] == ["DOCTOR_APPLICANT"]


async def test_duplicate_email_registration_rejected(client):
    await client.post("/api/v1/auth/register/patient", json=patient_payload())
    r = await client.post("/api/v1/auth/register/patient", json=patient_payload(mobileNumber="+258849999999"))
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "EMAIL_ALREADY_REGISTERED"


async def test_duplicate_mobile_registration_rejected(client):
    await client.post("/api/v1/auth/register/patient", json=patient_payload())
    r = await client.post(
        "/api/v1/auth/register/patient",
        json=patient_payload(email="different@example.com"),
    )
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "MOBILE_ALREADY_REGISTERED"


@pytest.mark.parametrize(
    "weak_password",
    ["short1!A", "alllowercase123!", "ALLUPPERCASE123!", "NoDigitsHere!", "NoSpecialChars123"],
)
async def test_weak_password_rejected(client, weak_password):
    r = await client.post("/api/v1/auth/register/patient", json=patient_payload(password=weak_password))
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "PASSWORD_POLICY_VIOLATION"


async def test_missing_consent_rejected(client):
    r = await client.post(
        "/api/v1/auth/register/patient", json=patient_payload(healthDataConsentAccepted=False)
    )
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "CONSENT_REQUIRED"


async def test_invalid_mobile_number_rejected(client):
    r = await client.post("/api/v1/auth/register/patient", json=patient_payload(mobileNumber="not-a-number"))
    assert r.status_code == 422


async def test_registration_requires_valid_email_format(client):
    r = await client.post("/api/v1/auth/register/patient", json=patient_payload(email="not-an-email"))
    assert r.status_code == 422


async def test_idempotency_key_returns_same_response_for_identical_request(client):
    headers = {"Idempotency-Key": "test-key-123"}
    r1 = await client.post("/api/v1/auth/register/patient", json=patient_payload(), headers=headers)
    r2 = await client.post("/api/v1/auth/register/patient", json=patient_payload(), headers=headers)
    assert r1.status_code == 201
    assert r2.status_code == 201
    assert r1.json() == r2.json()  # same userId returned, not a second user created


async def test_idempotency_key_reuse_with_different_body_is_rejected(client):
    headers = {"Idempotency-Key": "test-key-456"}
    await client.post("/api/v1/auth/register/patient", json=patient_payload(), headers=headers)
    r = await client.post(
        "/api/v1/auth/register/patient",
        json=patient_payload(email="someone-else@example.com", mobileNumber="+258840000000"),
        headers=headers,
    )
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "IDEMPOTENCY_KEY_REUSED"


async def test_registration_rate_limited_after_five_per_hour(client):
    for i in range(5):
        r = await client.post(
            "/api/v1/auth/register/patient",
            json=patient_payload(email=f"rl{i}@example.com", mobileNumber=f"+25884000000{i}"),
        )
        assert r.status_code == 201
    r = await client.post(
        "/api/v1/auth/register/patient",
        json=patient_payload(email="rl-overflow@example.com", mobileNumber="+258840000009"),
    )
    assert r.status_code == 429
    assert r.json()["error"]["code"] == "RATE_LIMITED"
