"""Multi-factor authentication endpoints."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends

from app.core.context import get_request_context
from app.core.envelope import ErrorEnvelope, SuccessEnvelope, success
from app.modules.identity.api.deps import CurrentAuth, get_authentication_service, get_mfa_service
from app.modules.identity.application.authentication_service import AuthenticationService
from app.modules.identity.application.mfa_service import MfaService
from app.modules.identity.application.schemas import (
    ConfirmAuthenticatorRequest,
    ConfirmAuthenticatorResponse,
    DisableMfaRequest,
    EnrolAuthenticatorResponse,
    VerifyMfaRequest,
)

router = APIRouter(
    prefix="/auth/mfa",
    tags=["Multi-Factor Authentication"],
    responses={422: {"model": ErrorEnvelope}},
)


@router.post(
    "/authenticator/enrol",
    response_model=SuccessEnvelope[EnrolAuthenticatorResponse],
    summary="Start authenticator-app (TOTP) enrolment",
)
async def enrol_authenticator(
    auth: CurrentAuth,
    service: Annotated[MfaService, Depends(get_mfa_service)],
):
    method, secret, otpauth_uri = await service.enrol_authenticator(auth.user)
    payload = EnrolAuthenticatorResponse(
        enrolment_id=method.id,
        secret=secret,
        otpauth_uri=otpauth_uri,
        expires_at=service.enrolment_expires_at(method),
    )
    return success(payload.model_dump(by_alias=True, mode="json"))


@router.post(
    "/authenticator/confirm",
    response_model=SuccessEnvelope[ConfirmAuthenticatorResponse],
    summary="Confirm authenticator enrolment with a TOTP code",
    responses={
        400: {"model": ErrorEnvelope, "description": "Enrolment expired or already confirmed"},
        401: {"model": ErrorEnvelope, "description": "Incorrect code"},
    },
)
async def confirm_authenticator(
    body: ConfirmAuthenticatorRequest,
    auth: CurrentAuth,
    service: Annotated[MfaService, Depends(get_mfa_service)],
):
    method, recovery_codes = await service.confirm_authenticator(auth.user, body.enrolment_id, body.code)
    payload = ConfirmAuthenticatorResponse(method_id=method.id, recovery_codes=recovery_codes)
    return success(payload.model_dump(by_alias=True, mode="json"))


@router.post(
    "/verify",
    summary="Complete login by verifying an MFA challenge",
    description="method is one of AUTHENTICATOR | SMS | EMAIL | RECOVERY_CODE.",
    responses={
        401: {"model": ErrorEnvelope, "description": "Incorrect code or expired challenge"},
    },
)
async def verify_mfa(
    body: VerifyMfaRequest,
    service: Annotated[AuthenticationService, Depends(get_authentication_service)],
):
    ctx = get_request_context()
    result = await service.complete_mfa_login(
        body.challenge_id, body.method, body.code, ip_address=ctx.ip_address, user_agent=ctx.user_agent
    )
    return success(result.model_dump(by_alias=True, mode="json"))


@router.post(
    "/recovery-codes/regenerate",
    summary="Regenerate recovery codes (invalidates all unused prior codes)",
    responses={401: {"model": ErrorEnvelope, "description": "Password confirmation required/incorrect"}},
)
async def regenerate_recovery_codes(
    body: DisableMfaRequest,  # reuses {currentPassword} shape
    auth: CurrentAuth,
    service: Annotated[MfaService, Depends(get_mfa_service)],
):
    codes = await service.regenerate_recovery_codes(auth.user, body.current_password)
    return success({"recoveryCodes": codes})


@router.delete(
    "/{method_id}",
    summary="Disable an MFA method",
    responses={
        401: {"model": ErrorEnvelope, "description": "Password confirmation required/incorrect"},
        409: {"model": ErrorEnvelope, "description": "Cannot disable the last mandatory MFA method"},
    },
)
async def disable_mfa(
    method_id: str,
    body: DisableMfaRequest,
    auth: CurrentAuth,
    service: Annotated[MfaService, Depends(get_mfa_service)],
):
    await service.disable_mfa(auth.user, uuid.UUID(method_id), body.current_password)
    return success({"disabled": True})
