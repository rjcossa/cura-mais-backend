"""Tests for password change/forgot/reset (spec section 25.5)."""

from __future__ import annotations

from tests.conftest import get_outbox_param, patient_payload

EMAIL = "ana.test@example.com"


async def _register_and_login(client):
    await client.post("/api/v1/auth/register/patient", json=patient_payload())
    r = await client.post(
        "/api/v1/auth/login", json={"email": EMAIL, "password": "SecurePassword@123", "device": {}}
    )
    return r.json()["data"]["accessToken"]


async def test_change_password_success(client):
    token = await _register_and_login(client)
    r = await client.post(
        "/api/v1/auth/password/change",
        headers={"Authorization": f"Bearer {token}"},
        json={"currentPassword": "SecurePassword@123", "newPassword": "AnotherSecureP@ss1"},
    )
    assert r.status_code == 200

    # New password works.
    r = await client.post(
        "/api/v1/auth/login", json={"email": EMAIL, "password": "AnotherSecureP@ss1", "device": {}}
    )
    assert r.status_code == 200


async def test_change_password_wrong_current_password(client):
    token = await _register_and_login(client)
    r = await client.post(
        "/api/v1/auth/password/change",
        headers={"Authorization": f"Bearer {token}"},
        json={"currentPassword": "WrongOne@123", "newPassword": "AnotherSecureP@ss1"},
    )
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "CURRENT_PASSWORD_INCORRECT"


async def test_change_password_rejects_reused_password(client):
    token = await _register_and_login(client)
    r = await client.post(
        "/api/v1/auth/password/change",
        headers={"Authorization": f"Bearer {token}"},
        json={"currentPassword": "SecurePassword@123", "newPassword": "SecurePassword@123"},
    )
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "NEW_PASSWORD_SAME_AS_CURRENT"


async def test_forgot_password_generic_response_for_unknown_email(client):
    r = await client.post("/api/v1/auth/password/forgot", json={"email": "nobody@example.com"})
    assert r.status_code == 200


async def test_forgot_and_reset_password_flow(client, session_factory):
    await client.post("/api/v1/auth/register/patient", json=patient_payload())
    await client.post("/api/v1/auth/password/forgot", json={"email": EMAIL})

    reset_url = await get_outbox_param(session_factory, EMAIL, "PasswordResetRequested", "resetUrl")
    reset_token = reset_url.split("token=")[1]

    r = await client.post(
        "/api/v1/auth/password/reset", json={"token": reset_token, "newPassword": "AnotherSecureP@ss1"}
    )
    assert r.status_code == 200

    # Old password no longer works, new one does.
    r = await client.post(
        "/api/v1/auth/login", json={"email": EMAIL, "password": "SecurePassword@123", "device": {}}
    )
    assert r.status_code == 401

    r = await client.post(
        "/api/v1/auth/login", json={"email": EMAIL, "password": "AnotherSecureP@ss1", "device": {}}
    )
    assert r.status_code == 200


async def test_reset_token_cannot_be_reused(client, session_factory):
    await client.post("/api/v1/auth/register/patient", json=patient_payload())
    await client.post("/api/v1/auth/password/forgot", json={"email": EMAIL})
    reset_url = await get_outbox_param(session_factory, EMAIL, "PasswordResetRequested", "resetUrl")
    reset_token = reset_url.split("token=")[1]

    await client.post(
        "/api/v1/auth/password/reset", json={"token": reset_token, "newPassword": "AnotherSecureP@ss1"}
    )
    r = await client.post(
        "/api/v1/auth/password/reset", json={"token": reset_token, "newPassword": "YetAnotherP@ss1"}
    )
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "PASSWORD_RESET_TOKEN_INVALID"


async def test_reset_password_revokes_all_sessions(client, session_factory):
    token = await _register_and_login(client)

    await client.post("/api/v1/auth/password/forgot", json={"email": EMAIL})
    reset_url = await get_outbox_param(session_factory, EMAIL, "PasswordResetRequested", "resetUrl")
    reset_token = reset_url.split("token=")[1]
    await client.post(
        "/api/v1/auth/password/reset", json={"token": reset_token, "newPassword": "AnotherSecureP@ss1"}
    )

    r = await client.get("/api/v1/users/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 401
