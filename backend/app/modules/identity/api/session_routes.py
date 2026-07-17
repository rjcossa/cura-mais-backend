"""Session listing/revocation endpoints."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends

from app.core.envelope import ErrorEnvelope, SuccessEnvelope, success
from app.modules.identity.api.deps import CurrentAuth, get_session_service
from app.modules.identity.application.schemas import SessionOut
from app.modules.identity.application.session_service import SessionService

router = APIRouter(
    prefix="/auth/sessions",
    tags=["Sessions"],
    responses={401: {"model": ErrorEnvelope}},
)


@router.get("", response_model=SuccessEnvelope[list[SessionOut]], summary="List active sessions")
async def list_sessions(
    auth: CurrentAuth,
    service: Annotated[SessionService, Depends(get_session_service)],
):
    sessions = await service.list_sessions(auth.user.id, auth.claims.session_id)
    return success([s.model_dump(by_alias=True, mode="json") for s in sessions])


@router.delete(
    "/{session_id}",
    summary="Revoke a session",
    responses={404: {"model": ErrorEnvelope, "description": "Session not found"}},
)
async def revoke_session(
    session_id: uuid.UUID,
    auth: CurrentAuth,
    service: Annotated[SessionService, Depends(get_session_service)],
):
    await service.revoke_session(auth.user.id, session_id)
    return success({"revoked": True})
