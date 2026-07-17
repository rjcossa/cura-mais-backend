"""Password change / forgot / reset endpoints."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.core.context import get_request_context
from app.core.envelope import ErrorEnvelope, success
from app.core.rate_limit import get_rate_limiter
from app.modules.identity.api.deps import CurrentAuth, get_password_service
from app.modules.identity.application.password_service import PasswordService
from app.modules.identity.application.schemas import (
    ChangePasswordRequest,
    ForgotPasswordRequest,
    ResetPasswordRequest,
)

router = APIRouter(
    prefix="/auth/password",
    tags=["Password"],
    responses={422: {"model": ErrorEnvelope}},
)


@router.post(
    "/change",
    summary="Change the current user's password",
    responses={401: {"model": ErrorEnvelope, "description": "Current password incorrect"}},
)
async def change_password(
    body: ChangePasswordRequest,
    auth: CurrentAuth,
    service: Annotated[PasswordService, Depends(get_password_service)],
):
    await service.change_password(
        auth.user, body.current_password, body.new_password, auth.claims.session_id
    )
    return success({"passwordChanged": True})


@router.post("/forgot", summary="Request a password reset link")
async def forgot_password(
    body: ForgotPasswordRequest,
    service: Annotated[PasswordService, Depends(get_password_service)],
):
    ctx = get_request_context()
    await get_rate_limiter().enforce("password_reset_request", body.email.lower(), ctx.ip_address or "unknown")

    await service.forgot_password(body.email)
    return success({"message": "If an account exists for this email, a reset link has been sent."})


@router.post(
    "/reset",
    summary="Reset a password using a reset token",
    responses={400: {"model": ErrorEnvelope, "description": "Token invalid or expired"}},
)
async def reset_password(
    body: ResetPasswordRequest,
    service: Annotated[PasswordService, Depends(get_password_service)],
):
    await service.reset_password(body.token, body.new_password)
    return success({"passwordReset": True})
