"""Aggregates every Onboarding route module under a single router that
`app.main` mounts at the API version prefix."""

from __future__ import annotations

from fastapi import APIRouter

from app.modules.onboarding.api import applicant_routes, backoffice_routes, decision_routes, review_routes

onboarding_router = APIRouter()
onboarding_router.include_router(applicant_routes.router)
onboarding_router.include_router(backoffice_routes.router)
onboarding_router.include_router(review_routes.router)
onboarding_router.include_router(decision_routes.router)
