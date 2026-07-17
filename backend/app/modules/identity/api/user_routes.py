"""Current-user profile endpoints."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.core.envelope import ErrorEnvelope, SuccessEnvelope, success
from app.modules.identity.api.deps import CurrentAuth, get_user_service
from app.modules.identity.application.schemas import (
    ChangeEmailRequest,
    ChangeMobileRequest,
    ConfirmEmailChangeRequest,
    ConfirmMobileChangeRequest,
    DeactivateAccountRequest,
    UpdateCurrentUserRequest,
    UserProfileOut,
)
from app.modules.identity.application.user_service import UserService

router = APIRouter(
    prefix="/users",
    tags=["Users"],
    responses={401: {"model": ErrorEnvelope}},
)


@router.get("/me", response_model=SuccessEnvelope[UserProfileOut], summary="Get the current user's profile")
async def get_current_user_profile(
    auth: CurrentAuth,
    service: Annotated[UserService, Depends(get_user_service)],
):
    profile = await service.get_profile(auth.user)
    return success(profile.model_dump(by_alias=True, mode="json"))


@router.patch(
    "/me",
    response_model=SuccessEnvelope[UserProfileOut],
    summary="Update preferred language / timezone",
    description=(
        "Only preferredLanguage and timezone are updated here. Email and mobile "
        "number changes go through their own re-verification flows: "
        "POST /users/me/email/change-request and POST /users/me/mobile/change-request."
    ),
)
async def update_current_user(
    body: UpdateCurrentUserRequest,
    auth: CurrentAuth,
    service: Annotated[UserService, Depends(get_user_service)],
):
    await service.update_profile(auth.user, body.preferred_language, body.timezone)
    profile = await service.get_profile(auth.user)
    return success(profile.model_dump(by_alias=True, mode="json"))


@router.post(
    "/me/email/change-request",
    summary="Request an email address change",
    responses={
        401: {"model": ErrorEnvelope, "description": "Current password incorrect"},
        409: {"model": ErrorEnvelope, "description": "Email already registered to another account"},
    },
)
async def request_email_change(
    body: ChangeEmailRequest,
    auth: CurrentAuth,
    service: Annotated[UserService, Depends(get_user_service)],
):
    await service.request_email_change(auth.user, body.new_email, body.current_password)
    return success({"message": "A confirmation link has been sent to the new email address."})


@router.post(
    "/me/email/confirm",
    summary="Confirm an email address change",
    responses={400: {"model": ErrorEnvelope, "description": "Token invalid, expired, or already used"}},
)
async def confirm_email_change(
    body: ConfirmEmailChangeRequest,
    auth: CurrentAuth,
    service: Annotated[UserService, Depends(get_user_service)],
):
    await service.confirm_email_change(auth.user, body.token)
    return success({"emailChanged": True})


@router.post(
    "/me/mobile/change-request",
    summary="Request a mobile number change",
    responses={
        401: {"model": ErrorEnvelope, "description": "Current password incorrect"},
        409: {"model": ErrorEnvelope, "description": "Mobile number already registered to another account"},
    },
)
async def request_mobile_change(
    body: ChangeMobileRequest,
    auth: CurrentAuth,
    service: Annotated[UserService, Depends(get_user_service)],
):
    await service.request_mobile_change(auth.user, body.new_mobile_number, body.current_password)
    return success({"message": "A verification code has been sent to the new mobile number."})


@router.post(
    "/me/mobile/confirm",
    summary="Confirm a mobile number change with the OTP",
    responses={
        400: {"model": ErrorEnvelope, "description": "Code expired"},
        401: {"model": ErrorEnvelope, "description": "Incorrect code"},
    },
)
async def confirm_mobile_change(
    body: ConfirmMobileChangeRequest,
    auth: CurrentAuth,
    service: Annotated[UserService, Depends(get_user_service)],
):
    await service.confirm_mobile_change(auth.user, body.mobile_number, body.code)
    return success({"mobileChanged": True})


@router.post(
    "/me/deactivate",
    summary="Deactivate the current user's account",
    responses={401: {"model": ErrorEnvelope, "description": "Current password incorrect"}},
)
async def deactivate_account(
    body: DeactivateAccountRequest,
    auth: CurrentAuth,
    service: Annotated[UserService, Depends(get_user_service)],
):
    await service.deactivate_account(auth.user, body.current_password)
    return success({"deactivated": True})
