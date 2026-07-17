"""Registration, login, token refresh, and logout endpoints."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import JSONResponse

from app.core.context import get_request_context
from app.core.envelope import ErrorEnvelope, SuccessEnvelope, success
from app.core.idempotency import get_idempotent_response, save_idempotent_response
from app.core.rate_limit import get_rate_limiter
from app.modules.identity.api.deps import (
    CurrentAuth,
    DbSession,
    get_authentication_service,
    get_registration_service,
    get_session_service,
    get_token_service,
)
from app.modules.identity.application.authentication_service import AuthenticationService
from app.modules.identity.application.registration_service import RegistrationService
from app.modules.identity.application.schemas import (
    DoctorRegisterRequest,
    LoginRequest,
    PatientRegisterRequest,
    RefreshTokenRequest,
    RegisterResponse,
    TokenPair,
)
from app.modules.identity.application.tokens import DeviceInfo, TokenService

router = APIRouter(
    prefix="/auth",
    tags=["Authentication"],
    responses={
        422: {"model": ErrorEnvelope, "description": "Validation error"},
        401: {"model": ErrorEnvelope, "description": "Authentication failed"},
        429: {"model": ErrorEnvelope, "description": "Rate limited"},
    },
)


@router.post(
    "/register/patient",
    response_model=SuccessEnvelope[RegisterResponse],
    status_code=201,
    summary="Register a new patient",
    responses={409: {"model": ErrorEnvelope, "description": "Email or mobile already registered"}},
)
async def register_patient(
    request: Request,
    body: PatientRegisterRequest,
    db: DbSession,
    service: Annotated[RegistrationService, Depends(get_registration_service)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
):
    ctx = get_request_context()
    await get_rate_limiter().enforce("registration", ctx.ip_address or "unknown")

    raw_body = await request.body()
    if idempotency_key:
        cached = await get_idempotent_response(db, "auth.register.patient", idempotency_key, raw_body)
        if cached is not None:
            return JSONResponse(status_code=cached.status, content=cached.body)

    result = await service.register_patient(body)
    body_out = success(result.model_dump(by_alias=True, mode="json"))

    if idempotency_key:
        await save_idempotent_response(db, "auth.register.patient", idempotency_key, raw_body, 201, body_out)
    return JSONResponse(status_code=201, content=body_out)


@router.post(
    "/register/doctor",
    response_model=SuccessEnvelope[RegisterResponse],
    status_code=201,
    summary="Register a new doctor applicant",
    responses={409: {"model": ErrorEnvelope, "description": "Email or mobile already registered"}},
)
async def register_doctor(
    request: Request,
    body: DoctorRegisterRequest,
    db: DbSession,
    service: Annotated[RegistrationService, Depends(get_registration_service)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
):
    ctx = get_request_context()
    await get_rate_limiter().enforce("registration", ctx.ip_address or "unknown")

    raw_body = await request.body()
    if idempotency_key:
        cached = await get_idempotent_response(db, "auth.register.doctor", idempotency_key, raw_body)
        if cached is not None:
            return JSONResponse(status_code=cached.status, content=cached.body)

    result = await service.register_doctor_applicant(body)
    body_out = success(result.model_dump(by_alias=True, mode="json"))

    if idempotency_key:
        await save_idempotent_response(db, "auth.register.doctor", idempotency_key, raw_body, 201, body_out)
    return JSONResponse(status_code=201, content=body_out)


@router.post(
    "/login",
    summary="Log in with email and password",
    description="Returns tokens directly, or an MFA challenge if the account has MFA enabled.",
    responses={
        200: {
            "description": "Either a token pair or an MFA challenge",
            "content": {
                "application/json": {
                    "examples": {
                        "success": {"value": {"success": True, "data": {"accessToken": "...", "refreshToken": "...", "tokenType": "Bearer", "expiresIn": 900, "mfaRequired": False}}},
                        "mfa_required": {"value": {"success": True, "data": {"mfaRequired": True, "challengeId": "8476985a-6856-4057-8f9d-b6f5cde09427", "methods": ["AUTHENTICATOR"]}}},
                    }
                }
            },
        },
        423: {"model": ErrorEnvelope, "description": "Account locked"},
        403: {"model": ErrorEnvelope, "description": "Account suspended or deactivated"},
    },
)
async def login(
    request: Request,
    body: LoginRequest,
    service: Annotated[AuthenticationService, Depends(get_authentication_service)],
):
    ctx = get_request_context()
    await get_rate_limiter().enforce("login", body.email.lower(), ctx.ip_address or "unknown")

    result = await service.login(
        body.email, body.password, body.device, ip_address=ctx.ip_address, user_agent=ctx.user_agent
    )
    return success(result.model_dump(by_alias=True, mode="json"))


@router.post(
    "/refresh",
    response_model=SuccessEnvelope[TokenPair],
    summary="Rotate a refresh token for a new access/refresh token pair",
    responses={401: {"model": ErrorEnvelope, "description": "Refresh token invalid, expired, revoked, or reused"}},
)
async def refresh_token(
    body: RefreshTokenRequest,
    token_service: Annotated[TokenService, Depends(get_token_service)],
):
    ctx = get_request_context()
    await get_rate_limiter().enforce("refresh_token", ctx.ip_address or "unknown")

    device = body.device
    device_info = DeviceInfo(
        device_id=device.device_id,
        device_name=device.device_name,
        platform=device.platform,
        app_version=device.app_version,
        ip_address=ctx.ip_address,
        user_agent=ctx.user_agent,
        remember_me=device.remember_me,
    )
    issued = await token_service.rotate_refresh_token(body.refresh_token, device_info)
    return success(
        TokenPair(
            access_token=issued.access_token,
            refresh_token=issued.raw_refresh_token,
            expires_in=issued.access_token_expires_in,
        ).model_dump(by_alias=True, mode="json")
    )


@router.post("/logout", summary="Log out the current session")
async def logout(
    auth: CurrentAuth,
    db: DbSession,
):
    service = get_session_service(db)
    await service.logout(auth.user.id, auth.claims.session_id)
    return success({"loggedOut": True})


@router.post("/logout-all", summary="Log out of all devices/sessions")
async def logout_all(auth: CurrentAuth, db: DbSession):
    service = get_session_service(db)
    await service.logout_all(auth.user.id)
    return success({"loggedOut": True})
