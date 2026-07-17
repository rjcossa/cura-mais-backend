"""Back-office administrative endpoints — role assignment and account
lifecycle (spec sections 16.4, 16.5). All require explicit permissions
rather than just "being logged in": these are the operations the back-office
portal (spec section 2.6) uses, not something an ordinary patient/provider
token should ever satisfy.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends

from app.core.envelope import ErrorEnvelope, success
from app.modules.identity.api.deps import CurrentAuth, get_role_service, require_permission
from app.modules.identity.application.role_service import RoleService
from app.modules.identity.application.schemas import AssignRoleRequest

router = APIRouter(
    prefix="/admin/users",
    tags=["Back-Office Administration"],
    responses={
        401: {"model": ErrorEnvelope},
        403: {"model": ErrorEnvelope, "description": "Missing required permission"},
    },
)


@router.post(
    "/{user_id}/roles",
    summary="Assign a role to a user",
    responses={
        404: {"model": ErrorEnvelope, "description": "Role or user not found"},
        409: {"model": ErrorEnvelope, "description": "Role already assigned"},
    },
)
async def assign_role(
    user_id: uuid.UUID,
    body: AssignRoleRequest,
    auth: Annotated[CurrentAuth, Depends(require_permission("ROLE_ASSIGN"))],
    service: Annotated[RoleService, Depends(get_role_service)],
):
    await service.assign_role(
        user_id, body.role_code, auth.user.id, expires_at=body.expires_at, reason=body.reason
    )
    return success({"assigned": True})


@router.delete(
    "/{user_id}/roles/{role_code}",
    summary="Revoke a role from a user",
    responses={404: {"model": ErrorEnvelope, "description": "Role not currently assigned"}},
)
async def revoke_role(
    user_id: uuid.UUID,
    role_code: str,
    auth: Annotated[CurrentAuth, Depends(require_permission("ROLE_REVOKE"))],
    service: Annotated[RoleService, Depends(get_role_service)],
):
    await service.revoke_role(user_id, role_code, auth.user.id)
    return success({"revoked": True})


@router.post("/{user_id}/suspend", summary="Suspend a user account")
async def suspend_user(
    user_id: uuid.UUID,
    reason: str,
    auth: Annotated[CurrentAuth, Depends(require_permission("USER_ADMIN_SUSPEND"))],
    service: Annotated[RoleService, Depends(get_role_service)],
):
    await service.suspend_user(user_id, reason, auth.user.id)
    return success({"suspended": True})


@router.post("/{user_id}/activate", summary="Reactivate a suspended/locked user account")
async def activate_user(
    user_id: uuid.UUID,
    auth: Annotated[CurrentAuth, Depends(require_permission("USER_ADMIN_ACTIVATE"))],
    service: Annotated[RoleService, Depends(get_role_service)],
):
    await service.activate_user(user_id, auth.user.id)
    return success({"activated": True})


@router.post(
    "/{user_id}/sessions/revoke-all",
    summary="Revoke every active session for a user",
)
async def revoke_all_user_sessions(
    user_id: uuid.UUID,
    auth: Annotated[CurrentAuth, Depends(require_permission("SESSION_ADMIN_REVOKE"))],
    service: Annotated[RoleService, Depends(get_role_service)],
):
    await service.revoke_all_sessions(user_id, reason="ADMIN_REVOKED_ALL")
    return success({"revoked": True})
