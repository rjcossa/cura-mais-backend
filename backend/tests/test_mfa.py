"""Tests for MFA enrolment, login challenges, and disabling (spec section
25.6)."""

from __future__ import annotations

import pyotp

from tests.conftest import patient_payload

EMAIL = "ana.test@example.com"


async def _register_and_login(client):
    await client.post("/api/v1/auth/register/patient", json=patient_payload())
    r = await client.post(
        "/api/v1/auth/login", json={"email": EMAIL, "password": "SecurePassword@123", "device": {}}
    )
    return r.json()["data"]["accessToken"]


async def _enrol_authenticator(client, token):
    r = await client.post("/api/v1/auth/mfa/authenticator/enrol", headers={"Authorization": f"Bearer {token}"})
    data = r.json()["data"]
    totp = pyotp.TOTP(data["secret"])
    r2 = await client.post(
        "/api/v1/auth/mfa/authenticator/confirm",
        headers={"Authorization": f"Bearer {token}"},
        json={"enrolmentId": data["enrolmentId"], "code": totp.now()},
    )
    confirm_data = r2.json()["data"]
    return totp, confirm_data["recoveryCodes"], confirm_data["methodId"]


async def test_authenticator_enrolment_returns_secret_and_uri(client):
    token = await _register_and_login(client)
    r = await client.post("/api/v1/auth/mfa/authenticator/enrol", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    data = r.json()["data"]
    assert "secret" in data
    assert data["otpauthUri"].startswith("otpauth://totp/")


async def test_confirm_authenticator_with_correct_code_enables_mfa_and_issues_recovery_codes(client):
    token = await _register_and_login(client)
    totp, recovery_codes, method_id = await _enrol_authenticator(client, token)
    assert len(recovery_codes) == 10
    assert all(len(c) == 14 for c in recovery_codes)  # XXXX-XXXX-XXXX


async def test_confirm_authenticator_with_wrong_code_rejected(client):
    token = await _register_and_login(client)
    r = await client.post("/api/v1/auth/mfa/authenticator/enrol", headers={"Authorization": f"Bearer {token}"})
    enrolment_id = r.json()["data"]["enrolmentId"]

    r2 = await client.post(
        "/api/v1/auth/mfa/authenticator/confirm",
        headers={"Authorization": f"Bearer {token}"},
        json={"enrolmentId": enrolment_id, "code": "000000"},
    )
    assert r2.status_code == 401
    assert r2.json()["error"]["code"] == "INVALID_MFA_CODE"


async def test_login_requires_mfa_once_enabled(client):
    token = await _register_and_login(client)
    await _enrol_authenticator(client, token)

    r = await client.post(
        "/api/v1/auth/login", json={"email": EMAIL, "password": "SecurePassword@123", "device": {}}
    )
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["mfaRequired"] is True
    assert "challengeId" in data
    assert data["methods"] == ["AUTHENTICATOR"]
    assert "accessToken" not in data


async def test_complete_login_with_correct_totp_code(client):
    token = await _register_and_login(client)
    totp, _, _ = await _enrol_authenticator(client, token)

    r = await client.post(
        "/api/v1/auth/login", json={"email": EMAIL, "password": "SecurePassword@123", "device": {}}
    )
    challenge_id = r.json()["data"]["challengeId"]

    r2 = await client.post(
        "/api/v1/auth/mfa/verify",
        json={"challengeId": challenge_id, "method": "AUTHENTICATOR", "code": totp.now()},
    )
    assert r2.status_code == 200
    assert "accessToken" in r2.json()["data"]


async def test_complete_login_with_recovery_code_then_it_cannot_be_reused(client):
    token = await _register_and_login(client)
    _, recovery_codes, _ = await _enrol_authenticator(client, token)

    r = await client.post(
        "/api/v1/auth/login", json={"email": EMAIL, "password": "SecurePassword@123", "device": {}}
    )
    challenge_id = r.json()["data"]["challengeId"]
    r2 = await client.post(
        "/api/v1/auth/mfa/verify",
        json={"challengeId": challenge_id, "method": "RECOVERY_CODE", "code": recovery_codes[0]},
    )
    assert r2.status_code == 200

    r = await client.post(
        "/api/v1/auth/login", json={"email": EMAIL, "password": "SecurePassword@123", "device": {}}
    )
    challenge_id2 = r.json()["data"]["challengeId"]
    r3 = await client.post(
        "/api/v1/auth/mfa/verify",
        json={"challengeId": challenge_id2, "method": "RECOVERY_CODE", "code": recovery_codes[0]},
    )
    assert r3.status_code == 401
    assert r3.json()["error"]["code"] == "INVALID_MFA_CODE"


async def test_disable_mfa_success_allows_login_without_challenge(client):
    token = await _register_and_login(client)
    _, _, method_id = await _enrol_authenticator(client, token)

    r = await client.request(
        "DELETE",
        f"/api/v1/auth/mfa/{method_id}",
        headers={"Authorization": f"Bearer {token}"},
        json={"currentPassword": "SecurePassword@123"},
    )
    assert r.status_code == 200

    r2 = await client.post(
        "/api/v1/auth/login", json={"email": EMAIL, "password": "SecurePassword@123", "device": {}}
    )
    assert r2.status_code == 200
    assert r2.json()["data"]["mfaRequired"] is False


async def test_disable_mfa_requires_correct_password(client):
    token = await _register_and_login(client)
    await _enrol_authenticator(client, token)

    # A made-up method id is enough to exercise the re-authentication gate,
    # since password verification happens before the method lookup.
    import uuid

    r = await client.request(
        "DELETE",
        f"/api/v1/auth/mfa/{uuid.uuid4()}",
        headers={"Authorization": f"Bearer {token}"},
        json={"currentPassword": "WrongPassword@1"},
    )
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "REAUTHENTICATION_REQUIRED"


async def test_patient_mfa_is_optional_not_mandatory(client):
    """Patients (unlike doctors/admins) are not in MANDATORY_MFA_ROLES, so
    they should be able to log in without ever enrolling MFA."""
    r = await client.post("/api/v1/auth/register/patient", json=patient_payload())
    assert r.status_code == 201
    r2 = await client.post(
        "/api/v1/auth/login", json={"email": EMAIL, "password": "SecurePassword@123", "device": {}}
    )
    assert r2.status_code == 200
    assert r2.json()["data"]["mfaRequired"] is False
