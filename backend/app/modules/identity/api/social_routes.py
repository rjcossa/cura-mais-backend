"""Social login, linking, and unlinking endpoints."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.core.context import get_request_context
from app.core.envelope import ErrorEnvelope, success
from app.core.rate_limit import get_rate_limiter
from app.modules.identity.api.deps import CurrentAuth, get_social_service
from app.modules.identity.application.schemas import LinkSocialProviderRequest, SocialLoginRequest
from app.modules.identity.application.social_service import SocialAuthService

router = APIRouter(
    prefix="/auth/social",
    tags=["Social Login"],
    responses={401: {"model": ErrorEnvelope, "description": "Social token could not be verified"}},
)


@router.post(
    "/login",
    summary="Log in or register via Google / Apple / Facebook",
    responses={409: {"model": ErrorEnvelope, "description": "An account with this email already exists"}},
)
async def social_login(
    body: SocialLoginRequest,
    service: Annotated[SocialAuthService, Depends(get_social_service)],
):
    ctx = get_request_context()
    await get_rate_limiter().enforce("social_login", ctx.ip_address or "unknown")

    result = await service.login_or_register(
        body.provider,
        body.identity_token,
        body.requested_account_type,
        body.device,
        nonce=body.nonce,
        ip_address=ctx.ip_address,
        user_agent=ctx.user_agent,
    )
    return success(result.model_dump(by_alias=True, mode="json"))


@router.post("/link", summary="Link an additional social provider to the current account")
async def link_social_provider(
    body: LinkSocialProviderRequest,
    auth: CurrentAuth,
    service: Annotated[SocialAuthService, Depends(get_social_service)],
):
    await service.link_provider(auth.user, body.provider, body.identity_token, nonce=body.nonce)
    return success({"linked": True})


@router.delete(
    "/{provider}",
    summary="Unlink a social provider",
    responses={
        409: {
            "model": ErrorEnvelope,
            "description": "Cannot remove your only remaining authentication method",
        }
    },
)
async def unlink_social_provider(
    provider: str,
    auth: CurrentAuth,
    service: Annotated[SocialAuthService, Depends(get_social_service)],
):
    await service.unlink_provider(auth.user, provider)
    return success({"unlinked": True})
