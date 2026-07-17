"""Aggregates every Identity route module under a single router that
`app.main` mounts at the API version prefix."""

from __future__ import annotations

from fastapi import APIRouter

from app.modules.identity.api import (
    admin_routes,
    auth_routes,
    mfa_routes,
    password_routes,
    session_routes,
    social_routes,
    user_routes,
    verification_routes,
)

identity_router = APIRouter()
identity_router.include_router(auth_routes.router)
identity_router.include_router(verification_routes.router)
identity_router.include_router(password_routes.router)
identity_router.include_router(mfa_routes.router)
identity_router.include_router(session_routes.router)
identity_router.include_router(social_routes.router)
identity_router.include_router(user_routes.router)
identity_router.include_router(admin_routes.router)
