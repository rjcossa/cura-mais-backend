"""Tests for session listing/revocation (spec section 25.9)."""

from __future__ import annotations

from tests.conftest import patient_payload

EMAIL = "ana.test@example.com"


async def _register(client):
    r = await client.post("/api/v1/auth/register/patient", json=patient_payload())
    assert r.status_code == 201


async def _login(client, device_name: str):
    r = await client.post(
        "/api/v1/auth/login",
        json={"email": EMAIL, "password": "SecurePassword@123", "device": {"deviceName": device_name}},
    )
    return r.json()["data"]["accessToken"]


async def test_list_sessions_shows_all_active_devices(client):
    await _register(client)
    token_a = await _login(client, "iPhone")
    await _login(client, "Chrome")

    r = await client.get("/api/v1/auth/sessions", headers={"Authorization": f"Bearer {token_a}"})
    assert r.status_code == 200
    sessions = r.json()["data"]
    assert len(sessions) == 2
    assert {s["deviceName"] for s in sessions} == {"iPhone", "Chrome"}
    assert sum(1 for s in sessions if s["current"]) == 1


async def test_revoke_own_session(client):
    await _register(client)
    token_a = await _login(client, "iPhone")
    await _login(client, "Chrome")

    sessions = (await client.get("/api/v1/auth/sessions", headers={"Authorization": f"Bearer {token_a}"})).json()["data"]
    other = next(s for s in sessions if not s["current"])

    r = await client.delete(f"/api/v1/auth/sessions/{other['id']}", headers={"Authorization": f"Bearer {token_a}"})
    assert r.status_code == 200

    sessions_after = (await client.get("/api/v1/auth/sessions", headers={"Authorization": f"Bearer {token_a}"})).json()["data"]
    assert len(sessions_after) == 1


async def test_cannot_revoke_another_users_session(client):
    await _register(client)
    token_a = await _login(client, "iPhone")

    other_payload = patient_payload(email="other@example.com", mobileNumber="+258840000001")
    await client.post("/api/v1/auth/register/patient", json=other_payload)
    other_login = await client.post(
        "/api/v1/auth/login",
        json={"email": other_payload["email"], "password": other_payload["password"], "device": {}},
    )
    other_token = other_login.json()["data"]["accessToken"]

    sessions = (await client.get("/api/v1/auth/sessions", headers={"Authorization": f"Bearer {token_a}"})).json()["data"]
    my_session_id = sessions[0]["id"]

    r = await client.delete(
        f"/api/v1/auth/sessions/{my_session_id}", headers={"Authorization": f"Bearer {other_token}"}
    )
    assert r.status_code == 404  # session not found *for this user*


async def test_logout_all_revokes_everything(client):
    await _register(client)
    token_a = await _login(client, "iPhone")
    await _login(client, "Chrome")

    r = await client.post("/api/v1/auth/logout-all", headers={"Authorization": f"Bearer {token_a}"})
    assert r.status_code == 200

    r2 = await client.get("/api/v1/users/me", headers={"Authorization": f"Bearer {token_a}"})
    assert r2.status_code == 401


async def test_logout_revokes_current_session_refresh_token(client):
    await _register(client)
    r = await client.post(
        "/api/v1/auth/login", json={"email": EMAIL, "password": "SecurePassword@123", "device": {}}
    )
    data = r.json()["data"]

    r2 = await client.post("/api/v1/auth/logout", headers={"Authorization": f"Bearer {data['accessToken']}"})
    assert r2.status_code == 200

    r3 = await client.post(
        "/api/v1/auth/refresh", json={"refreshToken": data["refreshToken"], "device": {}}
    )
    assert r3.status_code == 401
