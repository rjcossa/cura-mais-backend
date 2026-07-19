"""Aggregates every Providers module route file into a single router
mounted by `app.main` under `settings.api_v1_prefix`.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.modules.providers.api import (
    affiliations_routes,
    backoffice_routes,
    languages_routes,
    locations_routes,
    media_routes,
    profile_routes,
    public_routes,
    qualifications_routes,
    registrations_routes,
    services_routes,
    specialities_routes,
)

providers_router = APIRouter()

providers_router.include_router(profile_routes.router)
providers_router.include_router(registrations_routes.router)
providers_router.include_router(qualifications_routes.router)
providers_router.include_router(specialities_routes.reference_router)
providers_router.include_router(specialities_routes.router)
providers_router.include_router(languages_routes.router)
providers_router.include_router(services_routes.router)
providers_router.include_router(locations_routes.router)
providers_router.include_router(affiliations_routes.router)
providers_router.include_router(media_routes.router)
providers_router.include_router(public_routes.router)
providers_router.include_router(backoffice_routes.router)
