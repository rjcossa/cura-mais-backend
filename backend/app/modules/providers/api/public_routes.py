"""Public, unauthenticated provider profile routes (spec section 20).

Applies `provider_visibility_settings` (spec 5.8) so those settings are
actually functional rather than stored-but-unused. Only `VERIFIED`
specialities are shown publicly — spec 20.3 doesn't call this out
explicitly the way it does for qualifications, but showing a
self-declared, unverified speciality as if it were a credentialed fact on
a public profile would defeat the purpose of having verification at all.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from typing import Annotated

from app.core.envelope import ErrorEnvelope, success
from app.core.exceptions import NotFoundError
from app.modules.providers.api.deps import (
    get_affiliation_repo,
    get_language_repo,
    get_location_repo,
    get_provider_repo,
    get_service_repo,
    get_speciality_repo,
)
from app.modules.providers.application.schemas import (
    PublicAffiliationOut,
    PublicLanguageOut,
    PublicLocationOut,
    PublicProviderOut,
    PublicServiceOut,
    PublicSpecialityOut,
)
from app.modules.providers.domain.repositories import (
    AffiliationRepository,
    LanguageRepository,
    LocationRepository,
    ProviderRepository,
    ServiceRepository,
    SpecialityRepository,
)

router = APIRouter(prefix="/public/providers", tags=["Providers — Public"], responses={404: {"model": ErrorEnvelope}})

_VISIBLE_PUBLICATION_STATUSES = {"PUBLISHED"}


async def _build_public_dto(
    provider,
    provider_repo: ProviderRepository,
    speciality_repo: SpecialityRepository,
    language_repo: LanguageRepository,
    service_repo: ServiceRepository,
    location_repo: LocationRepository,
    affiliation_repo: AffiliationRepository,
) -> dict:
    visibility = await provider_repo.get_visibility_settings(provider.id)
    show_full_bio = visibility is None or visibility.show_full_biography
    show_years = visibility is None or visibility.show_years_of_experience
    show_affiliations = visibility is None or visibility.show_affiliations
    show_locations = visibility is None or visibility.show_locations
    show_languages = visibility is None or visibility.show_languages
    show_prices = visibility is None or visibility.show_service_prices

    assignments = [a for a in await speciality_repo.list_for_provider(provider.id) if a.verification_status == "VERIFIED"]
    speciality_lookup = {}
    for assignment in assignments:
        speciality = await speciality_repo.get_reference_by_id(assignment.speciality_id)
        if speciality is not None:
            speciality_lookup[assignment.id] = speciality

    primary_assignment = next((a for a in assignments if a.is_primary), None)
    primary_speciality = None
    if primary_assignment is not None and primary_assignment.id in speciality_lookup:
        s = speciality_lookup[primary_assignment.id]
        primary_speciality = PublicSpecialityOut(id=s.id, code=s.code, name=s.name)

    specialities = [
        PublicSpecialityOut(id=s.id, code=s.code, name=s.name) for s in speciality_lookup.values()
    ]

    languages = []
    if show_languages:
        languages = [
            PublicLanguageOut(code=lang.language_code)
            for lang in await language_repo.list_for_provider(provider.id)
            if lang.can_consult
        ]

    services = []
    for service in await service_repo.list_for_provider(provider.id, status="ACTIVE"):
        if not service.publicly_visible:
            continue
        modes = await service_repo.list_modes(service.id)
        services.append(
            PublicServiceOut(
                id=service.id,
                name=service.name,
                duration_minutes=service.duration_minutes,
                price=float(service.price) if (show_prices and service.price is not None) else None,
                currency=service.currency if show_prices else None,
                pro_bono=service.pro_bono,
                delivery_modes=modes,
            )
        )

    locations = []
    if show_locations:
        for location in await location_repo.list_for_provider(provider.id, active_only=True):
            if location.location_type == "VIRTUAL":
                continue
            locations.append(
                PublicLocationOut(id=location.id, name=location.name, city=location.city, province=location.province, country_code=location.country_code)
            )

    affiliations = []
    if show_affiliations:
        for affiliation in await affiliation_repo.list_for_provider(provider.id):
            if affiliation.status != "ACTIVE":
                continue
            affiliations.append(PublicAffiliationOut(institution_id=affiliation.institution_id, professional_position=affiliation.professional_position))

    out = PublicProviderOut(
        id=provider.id,
        provider_type=provider.provider_type,
        display_name=provider.display_name,
        slug=provider.slug,
        professional_title=provider.professional_title,
        short_biography=provider.short_biography,
        biography=provider.biography if show_full_bio else None,
        years_of_experience=provider.years_of_experience if show_years else None,
        verification_badge=provider.verification_status,
        primary_speciality=primary_speciality,
        specialities=specialities,
        languages=languages,
        services=services,
        locations=locations,
        affiliations=affiliations,
    )
    return out.model_dump(by_alias=True, mode="json")


def _assert_publicly_visible(provider) -> None:
    if provider is None or provider.publication_status not in _VISIBLE_PUBLICATION_STATUSES:
        raise NotFoundError("The requested provider was not found.")


@router.get("/{provider_id}", summary="Get a public provider profile by ID")
async def get_public_provider(
    provider_id: uuid.UUID,
    provider_repo: Annotated[ProviderRepository, Depends(get_provider_repo)],
    speciality_repo: Annotated[SpecialityRepository, Depends(get_speciality_repo)],
    language_repo: Annotated[LanguageRepository, Depends(get_language_repo)],
    service_repo: Annotated[ServiceRepository, Depends(get_service_repo)],
    location_repo: Annotated[LocationRepository, Depends(get_location_repo)],
    affiliation_repo: Annotated[AffiliationRepository, Depends(get_affiliation_repo)],
):
    provider = await provider_repo.get_by_id(provider_id)
    _assert_publicly_visible(provider)
    return success(
        await _build_public_dto(provider, provider_repo, speciality_repo, language_repo, service_repo, location_repo, affiliation_repo)
    )


@router.get("/slug/{slug}", summary="Get a public provider profile by slug")
async def get_public_provider_by_slug(
    slug: str,
    provider_repo: Annotated[ProviderRepository, Depends(get_provider_repo)],
    speciality_repo: Annotated[SpecialityRepository, Depends(get_speciality_repo)],
    language_repo: Annotated[LanguageRepository, Depends(get_language_repo)],
    service_repo: Annotated[ServiceRepository, Depends(get_service_repo)],
    location_repo: Annotated[LocationRepository, Depends(get_location_repo)],
    affiliation_repo: Annotated[AffiliationRepository, Depends(get_affiliation_repo)],
):
    provider = await provider_repo.get_by_slug(slug)
    _assert_publicly_visible(provider)
    return success(
        await _build_public_dto(provider, provider_repo, speciality_repo, language_repo, service_repo, location_repo, affiliation_repo)
    )
