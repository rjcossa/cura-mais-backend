"""Email and mobile verification endpoints."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.core.envelope import ErrorEnvelope, success
from app.core.rate_limit import get_rate_limiter
from app.modules.identity.api.deps import get_verification_service
from app.modules.identity.application.schemas import (
    ResendEmailVerificationRequest,
    SendOtpRequest,
    VerifyEmailRequest,
    VerifyOtpRequest,
)
from app.modules.identity.application.verification_service import VerificationService

router = APIRouter(
    prefix="/auth",
    tags=["Verification"],
    responses={422: {"model": ErrorEnvelope}},
)


@router.post("/email/resend-verification", summary="Resend the email verification link")
async def resend_email_verification(
    body: ResendEmailVerificationRequest,
    service: Annotated[VerificationService, Depends(get_verification_service)],
):
    await get_rate_limiter().enforce("email_verification_resend", body.email.lower())

    await service.resend_email_verification(body.email)
    return success({"message": "If an account exists for this email, a verification link has been sent."})


@router.post(
    "/email/verify",
    summary="Verify an email address",
    responses={400: {"model": ErrorEnvelope, "description": "Token invalid, expired, or already used"}},
)
async def verify_email(
    body: VerifyEmailRequest,
    service: Annotated[VerificationService, Depends(get_verification_service)],
):
    await service.verify_email(body.token)
    return success({"emailVerified": True})


@router.post("/mobile/send-otp", summary="Send a one-time code to a mobile number")
async def send_mobile_otp(
    body: SendOtpRequest,
    service: Annotated[VerificationService, Depends(get_verification_service)],
):
    await get_rate_limiter().enforce("mobile_otp_send", body.mobile_number)

    await service.send_mobile_otp(body.mobile_number, body.purpose)
    return success({"message": "If an account exists for this number, a verification code has been sent."})


@router.post(
    "/mobile/verify-otp",
    summary="Verify a mobile one-time code",
    responses={
        400: {"model": ErrorEnvelope, "description": "Code expired"},
        401: {"model": ErrorEnvelope, "description": "Incorrect code"},
        429: {"model": ErrorEnvelope, "description": "Too many incorrect attempts"},
    },
)
async def verify_mobile_otp(
    body: VerifyOtpRequest,
    service: Annotated[VerificationService, Depends(get_verification_service)],
):
    await service.verify_mobile_otp(body.mobile_number, body.code, body.purpose)
    return success({"mobileVerified": True})
