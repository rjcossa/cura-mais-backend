"""Tests for POST /auth/refresh and JWT claims (spec sections 25.3, 8.3)."""

from __future__ import annotations

import base64
import json

from tests.conftest import patient_payload

EMAIL = "ana.test@example.com"


async def _register_and_login(client):
    await client.post("/api/v1/auth/register/patient", json=patient_payload())
    r = await client.post(
        "/api/v1/auth/login", json={"email": EMAIL, "password": "SecurePassword@123", "device": {}}
    )
    return r.json()["data"]


def _decode_claims(jwt_token: str) -> dict:
    payload_b64 = jwt_token.split(".")[1]
    padded = payload_b64 + "=" * (-len(payload_b64) % 4)
    return json.loads(base64.urlsafe_b64decode(padded))


async def test_access_token_contains_required_claims(client):
    tokens = await _register_and_login(client)
    claims = _decode_claims(tokens["accessToken"])

    for key in [
        "sub", "sid", "roles", "permissions", "email_verified", "mobile_verified",
        "mfa_verified", "token_version", "iat", "nbf", "exp", "iss", "aud", "jti",
    ]:
        assert key in claims, f"missing claim {key}"

    assert claims["roles"] == ["PATIENT"]
    assert claims["iss"] == "health-platform-identity"
    assert claims["aud"] == "health-platform-api"


async def test_access_token_excludes_prohibited_data(client):
    tokens = await _register_and_login(client)
    claims = _decode_claims(tokens["accessToken"])
    raw = json.dumps(claims)
    for forbidden in ["password", "national", "certificate", "address"]:
        assert forbidden not in raw.lower()


async def test_refresh_token_rotation_issues_new_pair(client):
    tokens = await _register_and_login(client)
    r = await client.post(
        "/api/v1/auth/refresh", json={"refreshToken": tokens["refreshToken"], "device": {}}
    )
    assert r.status_code == 200
    new_tokens = r.json()["data"]
    assert new_tokens["accessToken"] != tokens["accessToken"]
    assert new_tokens["refreshToken"] != tokens["refreshToken"]


async def test_refresh_token_reuse_is_detected_and_revokes_family(client):
    tokens = await _register_and_login(client)
    old_refresh = tokens["refreshToken"]

    r1 = await client.post("/api/v1/auth/refresh", json={"refreshToken": old_refresh, "device": {}})
    assert r1.status_code == 200
    new_refresh = r1.json()["data"]["refreshToken"]

    # Reusing the OLD (already rotated) token is treated as theft.
    r2 = await client.post("/api/v1/auth/refresh", json={"refreshToken": old_refresh, "device": {}})
    assert r2.status_code == 401
    assert r2.json()["error"]["code"] == "REFRESH_TOKEN_REUSE_DETECTED"

    # The entire family (including the token issued by the rotation above)
    # must now be revoked too.
    r3 = await client.post("/api/v1/auth/refresh", json={"refreshToken": new_refresh, "device": {}})
    assert r3.status_code == 401


async def test_unknown_refresh_token_rejected(client):
    r = await client.post(
        "/api/v1/auth/refresh", json={"refreshToken": "not-a-real-token-at-all", "device": {}}
    )
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "REFRESH_TOKEN_INVALID"


async def test_expired_access_token_rejected_by_protected_endpoint(client):
    # A syntactically-plausible but garbage token should be rejected as
    # invalid rather than crash the auth dependency.
    r = await client.get("/api/v1/users/me", headers={"Authorization": "Bearer not.a.jwt"})
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "ACCESS_TOKEN_INVALID"


async def test_missing_authorization_header_rejected(client):
    r = await client.get("/api/v1/users/me")
    assert r.status_code == 401


async def test_token_version_bump_invalidates_old_access_token(client, session_factory):
    tokens = await _register_and_login(client)

    # Changing the password bumps token_version and revokes sessions.
    r = await client.post(
        "/api/v1/auth/password/change",
        headers={"Authorization": f"Bearer {tokens['accessToken']}"},
        json={"currentPassword": "SecurePassword@123", "newPassword": "AnotherSecureP@ss1"},
    )
    assert r.status_code == 200

    # The OLD access token (pre-dating the password change) must now be
    # rejected even though it hasn't naturally expired yet.
    r = await client.get("/api/v1/users/me", headers={"Authorization": f"Bearer {tokens['accessToken']}"})
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "ACCESS_TOKEN_INVALID"
