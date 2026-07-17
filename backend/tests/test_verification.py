"""Tests for email verification and mobile OTP verification (spec
sections 25.4, section 12)."""

from __future__ import annotations

from tests.conftest import get_outbox_param, patient_payload

EMAIL = "ana.test@example.com"
MOBILE = "+258841234567"


async def _register(client):
    r = await client.post("/api/v1/auth/register/patient", json=patient_payload())
    assert r.status_code == 201


async def test_valid_email_verification_succeeds(client, session_factory):
    await _register(client)
    verify_url = await get_outbox_param(session_factory, EMAIL, "EmailVerificationRequested", "verificationUrl")
    token = verify_url.split("token=")[1]

    r = await client.post("/api/v1/auth/email/verify", json={"token": token})
    assert r.status_code == 200
    assert r.json()["data"]["emailVerified"] is True


async def test_email_verification_token_cannot_be_reused(client, session_factory):
    await _register(client)
    verify_url = await get_outbox_param(session_factory, EMAIL, "EmailVerificationRequested", "verificationUrl")
    token = verify_url.split("token=")[1]

    await client.post("/api/v1/auth/email/verify", json={"token": token})
    r = await client.post("/api/v1/auth/email/verify", json={"token": token})
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "VERIFICATION_TOKEN_USED"


async def test_invalid_email_token_rejected(client):
    r = await client.post("/api/v1/auth/email/verify", json={"token": "totally-made-up"})
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "VERIFICATION_TOKEN_INVALID"


async def test_resend_email_verification_returns_generic_response_for_unknown_email(client):
    r = await client.post("/api/v1/auth/email/resend-verification", json={"email": "nobody@example.com"})
    assert r.status_code == 200  # Never reveals whether the account exists.


async def test_valid_mobile_otp_verification_succeeds(client, session_factory):
    await _register(client)
    otp = await get_outbox_param(session_factory, MOBILE, "MobileVerificationRequested", "code")

    r = await client.post("/api/v1/auth/mobile/verify-otp", json={"mobileNumber": MOBILE, "code": otp})
    assert r.status_code == 200
    assert r.json()["data"]["mobileVerified"] is True


async def test_incorrect_otp_rejected(client):
    await _register(client)
    r = await client.post("/api/v1/auth/mobile/verify-otp", json={"mobileNumber": MOBILE, "code": "000000"})
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "OTP_INVALID"


async def test_otp_max_attempts_exceeded(client):
    await _register(client)
    for _ in range(5):
        r = await client.post("/api/v1/auth/mobile/verify-otp", json={"mobileNumber": MOBILE, "code": "000000"})
    assert r.status_code == 429
    assert r.json()["error"]["code"] == "OTP_MAX_ATTEMPTS_EXCEEDED"

    # Even the CORRECT code is now rejected because the token is invalidated.
    from app.core.rate_limit import get_rate_limiter

    get_rate_limiter().reset()  # isolate from the generic per-endpoint limiter, if any


async def test_account_activates_once_both_email_and_mobile_verified(client, session_factory):
    from sqlalchemy import select

    from app.modules.identity.domain.models import User

    await _register(client)
    verify_url = await get_outbox_param(session_factory, EMAIL, "EmailVerificationRequested", "verificationUrl")
    await client.post("/api/v1/auth/email/verify", json={"token": verify_url.split("token=")[1]})

    async with session_factory() as session:
        user = (await session.execute(select(User).where(User.email == EMAIL))).scalar_one()
        assert user.account_status == "PENDING_VERIFICATION"  # mobile still unverified

    otp = await get_outbox_param(session_factory, MOBILE, "MobileVerificationRequested", "code")
    await client.post("/api/v1/auth/mobile/verify-otp", json={"mobileNumber": MOBILE, "code": otp})

    async with session_factory() as session:
        user = (await session.execute(select(User).where(User.email == EMAIL))).scalar_one()
        assert user.account_status == "ACTIVE"
