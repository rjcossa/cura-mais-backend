"""Back-office provider administration routes (spec section 22), plus the
institution confirm/reject stand-in for affiliations (spec 17.7 — see
`application/affiliation_service.py`'s docstring for why this lives here
rather than behind a real Institution-module integration).
"""

from __future__ import annotations

import math
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.core.envelope import ErrorEnvelope, success
from app.modules.identity.api.deps import require_permission
from app.modules.providers.api.deps import (
    CurrentAuth,
    DbSession,
    flush_and_refresh,
    get_affiliation_repo,
    get_affiliation_service,
    get_location_repo,
    get_profile_service,
    get_provider_repo,
    get_qualification_repo,
    get_registration_repo,
    get_service_offering_service,
    get_service_repo,
    get_speciality_repo,
)
from app.modules.providers.application.affiliation_service import AffiliationService
from app.modules.providers.application.profile_service import ProfileService
from app.modules.providers.application.schemas import (
    AffiliationOut,
    CorrectProviderRequest,
    HideProviderRequest,
    LocationOut,
    PagedProvidersOut,
    ProviderProfileOut,
    ProviderSearchResultOut,
    PublicationHistoryOut,
    QualificationOut,
    ProviderSpecialityOut,
    RegistrationOut,
    RejectAffiliationRequest,
    ReinstateProviderRequest,
    ServiceOut,
    StatusHistoryOut,
    SuspendProviderRequest,
)
from app.modules.providers.application.service_offering_service import ServiceOfferingService
from app.modules.providers.domain.repositories import (
    AffiliationRepository,
    LocationRepository,
    ProviderRepository,
    QualificationRepository,
    RegistrationRepository,
    ServiceRepository,
    SpecialityRepository,
)

router = APIRouter(
    prefix="/back-office/providers",
    tags=["Providers — Back Office"],
    responses={401: {"model": ErrorEnvelope}, 403: {"model": ErrorEnvelope}},
)


def _profile_out(provider) -> dict:
    return ProviderProfileOut.model_validate(provider, from_attributes=True).model_dump(by_alias=True, mode="json")


@router.get("", summary="Search providers", dependencies=[Depends(require_permission("PROVIDER_SEARCH"))])
async def search_providers(
    provider_repo: Annotated[ProviderRepository, Depends(get_provider_repo)],
    provider_type: Annotated[str | None, Query(alias="providerType")] = None,
    verification_status: Annotated[str | None, Query(alias="verificationStatus")] = None,
    profile_status: Annotated[str | None, Query(alias="profileStatus")] = None,
    publication_status: Annotated[str | None, Query(alias="publicationStatus")] = None,
    speciality_id: Annotated[uuid.UUID | None, Query(alias="specialityId")] = None,
    institution_id: Annotated[uuid.UUID | None, Query(alias="institutionId")] = None,
    registration_number: Annotated[str | None, Query(alias="registrationNumber")] = None,
    name: Annotated[str | None, Query()] = None,
    page: Annotated[int, Query(ge=0)] = 0,
    size: Annotated[int, Query(ge=1, le=100)] = 20,
    sort: Annotated[str | None, Query()] = None,
):
    rows, total = await provider_repo.search(
        provider_type=provider_type,
        verification_status=verification_status,
        profile_status=profile_status,
        publication_status=publication_status,
        speciality_id=speciality_id,
        institution_id=institution_id,
        registration_number=registration_number,
        name=name,
        page=page,
        size=size,
        sort=sort,
    )
    content = [ProviderSearchResultOut.model_validate(p, from_attributes=True) for p in rows]
    out = PagedProvidersOut(
        content=content, page=page, size=size, total_elements=total, total_pages=max(1, math.ceil(total / size)) if total else 0
    )
    return success(out.model_dump(by_alias=True, mode="json"))


@router.get("/{provider_id}", summary="Get provider detail", dependencies=[Depends(require_permission("PROVIDER_READ"))])
async def get_provider_detail(
    provider_id: uuid.UUID,
    profile_service: Annotated[ProfileService, Depends(get_profile_service)],
    registration_repo: Annotated[RegistrationRepository, Depends(get_registration_repo)],
    qualification_repo: Annotated[QualificationRepository, Depends(get_qualification_repo)],
    speciality_repo: Annotated[SpecialityRepository, Depends(get_speciality_repo)],
    service_repo: Annotated[ServiceRepository, Depends(get_service_repo)],
    location_repo: Annotated[LocationRepository, Depends(get_location_repo)],
    affiliation_repo: Annotated[AffiliationRepository, Depends(get_affiliation_repo)],
    provider_repo: Annotated[ProviderRepository, Depends(get_provider_repo)],
):
    provider = await profile_service.get_provider(provider_id)
    registrations = await registration_repo.list_for_provider(provider_id)
    qualifications = await qualification_repo.list_for_provider(provider_id)
    specialities = await speciality_repo.list_for_provider(provider_id)
    services = await service_repo.list_for_provider(provider_id)
    locations = await location_repo.list_for_provider(provider_id)
    affiliations = await affiliation_repo.list_for_provider(provider_id)
    status_history = await provider_repo.list_status_history(provider_id)
    publication_history = await provider_repo.list_publication_history(provider_id)

    services_out = []
    for service in services:
        modes = await service_repo.list_modes(service.id)
        s_out = ServiceOut.model_validate(service, from_attributes=True)
        s_out.delivery_modes = modes
        services_out.append(s_out.model_dump(by_alias=True, mode="json"))

    return success(
        {
            "provider": _profile_out(provider),
            "registrations": [RegistrationOut.model_validate(r, from_attributes=True).model_dump(by_alias=True, mode="json") for r in registrations],
            "qualifications": [QualificationOut.model_validate(q, from_attributes=True).model_dump(by_alias=True, mode="json") for q in qualifications],
            "specialities": [ProviderSpecialityOut.model_validate(s, from_attributes=True).model_dump(by_alias=True, mode="json") for s in specialities],
            "services": services_out,
            "locations": [LocationOut.model_validate(loc, from_attributes=True).model_dump(by_alias=True, mode="json") for loc in locations],
            "affiliations": [AffiliationOut.model_validate(a, from_attributes=True).model_dump(by_alias=True, mode="json") for a in affiliations],
            "statusHistory": [StatusHistoryOut.model_validate(h, from_attributes=True).model_dump(by_alias=True, mode="json") for h in status_history],
            "publicationHistory": [PublicationHistoryOut.model_validate(h, from_attributes=True).model_dump(by_alias=True, mode="json") for h in publication_history],
        }
    )


@router.get(
    "/{provider_id}/status-history",
    summary="Get provider status history",
    dependencies=[Depends(require_permission("PROVIDER_STATUS_HISTORY_READ"))],
)
async def get_status_history(provider_id: uuid.UUID, provider_repo: Annotated[ProviderRepository, Depends(get_provider_repo)]):
    history = await provider_repo.list_status_history(provider_id)
    return success([StatusHistoryOut.model_validate(h, from_attributes=True).model_dump(by_alias=True, mode="json") for h in history])


@router.get(
    "/{provider_id}/publication-history",
    summary="Get provider publication history",
    dependencies=[Depends(require_permission("PROVIDER_PUBLICATION_HISTORY_READ"))],
)
async def get_publication_history(provider_id: uuid.UUID, provider_repo: Annotated[ProviderRepository, Depends(get_provider_repo)]):
    history = await provider_repo.list_publication_history(provider_id)
    return success([PublicationHistoryOut.model_validate(h, from_attributes=True).model_dump(by_alias=True, mode="json") for h in history])


@router.patch("/{provider_id}", summary="Correct provider data", dependencies=[Depends(require_permission("PROVIDER_CORRECT"))])
async def correct_provider(
    provider_id: uuid.UUID,
    body: CorrectProviderRequest,
    db: DbSession,
    profile_service: Annotated[ProfileService, Depends(get_profile_service)],
):
    provider = await profile_service.get_provider(provider_id)
    provider, _material_change = await profile_service.update_profile(
        provider, updates=body.updates, expected_version=body.version, reason=body.reason
    )
    await flush_and_refresh(db, provider)
    return success(_profile_out(provider))


@router.post("/{provider_id}/suspend", summary="Suspend a provider profile", dependencies=[Depends(require_permission("PROVIDER_SUSPEND"))])
async def suspend_provider(
    provider_id: uuid.UUID,
    body: SuspendProviderRequest,
    auth: CurrentAuth,
    db: DbSession,
    profile_service: Annotated[ProfileService, Depends(get_profile_service)],
    service_offering_service: Annotated[ServiceOfferingService, Depends(get_service_offering_service)],
):
    provider = await profile_service.get_provider(provider_id)
    await profile_service.suspend_provider(
        provider,
        reason_code=body.reason_code,
        comments=body.comments,
        source_type="BACK_OFFICE",
        source_reference=body.source_reference,
        changed_by=auth.user.id,
    )
    await service_offering_service.suspend_all_active(provider.id)
    await flush_and_refresh(db, provider)
    return success(_profile_out(provider))


@router.post("/{provider_id}/reinstate", summary="Reinstate a provider", dependencies=[Depends(require_permission("PROVIDER_REINSTATE"))])
async def reinstate_provider(
    provider_id: uuid.UUID,
    body: ReinstateProviderRequest,
    auth: CurrentAuth,
    db: DbSession,
    profile_service: Annotated[ProfileService, Depends(get_profile_service)],
):
    provider = await profile_service.get_provider(provider_id)
    await profile_service.reinstate_provider(
        provider, approval_reference=body.approval_reference, source_reference=body.comments, changed_by=auth.user.id
    )
    await flush_and_refresh(db, provider)
    return success(_profile_out(provider))


@router.post("/{provider_id}/hide", summary="Administratively hide a provider profile", dependencies=[Depends(require_permission("PROVIDER_HIDE"))])
async def hide_provider(
    provider_id: uuid.UUID,
    body: HideProviderRequest,
    auth: CurrentAuth,
    db: DbSession,
    profile_service: Annotated[ProfileService, Depends(get_profile_service)],
):
    provider = await profile_service.get_provider(provider_id)
    await profile_service.hide_provider(provider, reason_code=body.reason_code, comments=body.comments, changed_by=auth.user.id)
    await flush_and_refresh(db, provider)
    return success(_profile_out(provider))


@router.post(
    "/{provider_id}/affiliations/{affiliation_id}/confirm",
    summary="Confirm an affiliation (institution stand-in)",
    dependencies=[Depends(require_permission("PROVIDER_AFFILIATION_CONFIRM"))],
)
async def confirm_affiliation(
    provider_id: uuid.UUID,
    affiliation_id: uuid.UUID,
    auth: CurrentAuth,
    db: DbSession,
    affiliation_service: Annotated[AffiliationService, Depends(get_affiliation_service)],
):
    affiliation = await affiliation_service.get_owned(provider_id, affiliation_id)
    affiliation = await affiliation_service.confirm(affiliation, confirmed_by=auth.user.id)
    await flush_and_refresh(db, affiliation)
    return success(AffiliationOut.model_validate(affiliation, from_attributes=True).model_dump(by_alias=True, mode="json"))


@router.post(
    "/{provider_id}/affiliations/{affiliation_id}/reject",
    summary="Reject an affiliation (institution stand-in)",
    dependencies=[Depends(require_permission("PROVIDER_AFFILIATION_REJECT"))],
)
async def reject_affiliation(
    provider_id: uuid.UUID,
    affiliation_id: uuid.UUID,
    body: RejectAffiliationRequest,
    db: DbSession,
    affiliation_service: Annotated[AffiliationService, Depends(get_affiliation_service)],
):
    affiliation = await affiliation_service.get_owned(provider_id, affiliation_id)
    affiliation = await affiliation_service.reject(affiliation, reason=body.reason)
    await flush_and_refresh(db, affiliation)
    return success(AffiliationOut.model_validate(affiliation, from_attributes=True).model_dump(by_alias=True, mode="json"))
