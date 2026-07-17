"""Tests for POST /auth/login (spec section 25.2)."""

from __future__ import annotations

from sqlalchemy import select

from app.modules.identity.domain.models import User
from tests.conftest import patient_payload

pytestmark_email = "ana.test@example.com"


async def _register(client):
    r = await client.post("/api/v1/auth/register/patient", json=patient_payload())
    assert r.status_code == 201


async def test_successful_login_without_mfa(client):
    await _register(client)
    r = await client.post(
        "/api/v1/auth/login",
        json={"email": pytestmark_email, "password": "SecurePassword@123", "device": {"deviceName": "pytest"}},
    )
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["mfaRequired"] is False
    assert "accessToken" in data
    assert "refreshToken" in data
    assert data["tokenType"] == "Bearer"
    assert data["expiresIn"] == 900


async def test_invalid_password_returns_generic_error_and_increments_counter(client, session_factory):
    await _register(client)
    r = await client.post(
        "/api/v1/auth/login", json={"email": pytestmark_email, "password": "WrongPassword@1", "device": {}}
    )
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "INVALID_CREDENTIALS"

    async with session_factory() as session:
        user = (await session.execute(select(User).where(User.email == pytestmark_email))).scalar_one()
        assert user.failed_login_attempts == 1


async def test_unknown_email_returns_same_error_as_invalid_password(client):
    """Prevents account enumeration (spec 7.2)."""
    r = await client.post(
        "/api/v1/auth/login", json={"email": "nobody@example.com", "password": "SecurePassword@123", "device": {}}
    )
    assert r.status_code == 401
    assert r.json()["error"] == {
        "code": "INVALID_CREDENTIALS",
        "message": "The email address or password is incorrect.",
    }


async def test_account_locked_after_five_failed_attempts(client, session_factory):
    await _register(client)
    for _ in range(5):
        r = await client.post(
            "/api/v1/auth/login",
            json={"email": pytestmark_email, "password": "WrongPassword@1", "device": {}},
        )
        assert r.status_code == 401

    # The rate limiter (also 5/15min per spec 23.4) would otherwise fire on
    # this next call too — reset it so this test isolates account-lockout
    # behaviour specifically (rate limiting is covered by its own test).
    from app.core.rate_limit import get_rate_limiter

    get_rate_limiter().reset()

    # Even the CORRECT password is now rejected.
    r = await client.post(
        "/api/v1/auth/login",
        json={"email": pytestmark_email, "password": "SecurePassword@123", "device": {}},
    )
    assert r.status_code == 423
    assert r.json()["error"]["code"] == "ACCOUNT_LOCKED"

    async with session_factory() as session:
        user = (await session.execute(select(User).where(User.email == pytestmark_email))).scalar_one()
        assert user.account_status == "LOCKED"
        assert user.locked_until is not None


async def test_successful_login_resets_failed_attempt_counter(client, session_factory):
    await _register(client)
    await client.post(
        "/api/v1/auth/login", json={"email": pytestmark_email, "password": "WrongPassword@1", "device": {}}
    )
    r = await client.post(
        "/api/v1/auth/login",
        json={"email": pytestmark_email, "password": "SecurePassword@123", "device": {}},
    )
    assert r.status_code == 200

    async with session_factory() as session:
        user = (await session.execute(select(User).where(User.email == pytestmark_email))).scalar_one()
        assert user.failed_login_attempts == 0


async def test_suspended_account_cannot_login(client, session_factory):
    await _register(client)
    async with session_factory() as session:
        user = (await session.execute(select(User).where(User.email == pytestmark_email))).scalar_one()
        user.account_status = "SUSPENDED"
        await session.commit()

    r = await client.post(
        "/api/v1/auth/login",
        json={"email": pytestmark_email, "password": "SecurePassword@123", "device": {}},
    )
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "ACCOUNT_SUSPENDED"


async def test_deactivated_account_cannot_login(client, session_factory):
    await _register(client)
    async with session_factory() as session:
        user = (await session.execute(select(User).where(User.email == pytestmark_email))).scalar_one()
        user.account_status = "DEACTIVATED"
        await session.commit()

    r = await client.post(
        "/api/v1/auth/login",
        json={"email": pytestmark_email, "password": "SecurePassword@123", "device": {}},
    )
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "ACCOUNT_DEACTIVATED"


async def test_login_rate_limited_after_five_attempts_same_account_and_ip(client):
    await _register(client)
    for _ in range(5):
        await client.post(
            "/api/v1/auth/login", json={"email": pytestmark_email, "password": "WrongPassword@1", "device": {}}
        )
    r = await client.post(
        "/api/v1/auth/login", json={"email": pytestmark_email, "password": "SecurePassword@123", "device": {}}
    )
    assert r.status_code == 429
