"""FastAPI dependency wiring for the Providers module. Same rationale as
`app.modules.identity.api.deps` / `app.modules.onboarding.api.deps`: each
factory builds a fresh set of repositories bound to the current request's
`AsyncSession`.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.modules.identity.api.deps import CurrentAuth
from app.modules.identity.application.identity_ports import IdentityQueryService
from app.modules.identity.infrastructure.repositories import SqlAlchemyRoleRepository, SqlAlchemyUserRepository
from app.modules.providers.application.affiliation_service import AffiliationService
from app.modules.providers.application.completeness_service import CompletenessService
from app.modules.providers.application.language_service import LanguageService
from app.modules.providers.application.location_service import LocationService
from app.modules.providers.application.media_service import MediaService
from app.modules.providers.application.professional_registration_service import ProfessionalRegistrationService
from app.modules.providers.application.profile_service import ProfileService
from app.modules.providers.application.publication_service import PublicationService
from app.modules.providers.application.qualification_service import QualificationService
from app.modules.providers.application.service_offering_service import ServiceOfferingService
from app.modules.providers.application.speciality_service import SpecialityService
from app.modules.providers.infrastructure.identity_adapter import IdentityAdapter
from app.modules.providers.infrastructure.repositories import (
    SqlAlchemyAffiliationRepository,
    SqlAlchemyExternalIdentifierRepository,
    SqlAlchemyLanguageRepository,
    SqlAlchemyLocationRepository,
    SqlAlchemyMediaRepository,
    SqlAlchemyOutboxRepository,
    SqlAlchemyProviderRepository,
    SqlAlchemyQualificationRepository,
    SqlAlchemyRegistrationRepository,
    SqlAlchemyServiceRepository,
    SqlAlchemySpecialityRepository,
)
from app.shared.documents.port import get_document_adapter

DbSession = Annotated[AsyncSession, Depends(get_db)]


async def flush_and_refresh(db: AsyncSession, *objects) -> None:
    """Call after a route mutates an already-persistent entity (not a
    fresh `add()`) and is about to serialize it in the response.

    SQLAlchemy eagerly populates `server_default`-driven columns (like
    `created_at`) via RETURNING right after `INSERT` + `flush()` — but for
    an `UPDATE` (an entity whose attributes were changed via plain
    `setattr`), `onupdate`-driven columns like `updated_at` and the
    `version_id_col` counter are left *expired* after `flush()`, not
    populated. Accessing them afterward without an explicit, awaited
    `refresh()` trips `sqlalchemy.exc.MissingGreenlet`, since the
    attribute's implicit lazy-reload can't run outside an awaited call
    under the async driver. Confirmed empirically (not assumed) before
    writing this: INSERT-then-flush is safe, UPDATE-then-flush is not.
    """
    await db.flush()
    for obj in objects:
        await db.refresh(obj)


def _repos(db: AsyncSession):
    return {
        "provider": SqlAlchemyProviderRepository(db),
        "registration": SqlAlchemyRegistrationRepository(db),
        "qualification": SqlAlchemyQualificationRepository(db),
        "speciality": SqlAlchemySpecialityRepository(db),
        "language": SqlAlchemyLanguageRepository(db),
        "service": SqlAlchemyServiceRepository(db),
        "location": SqlAlchemyLocationRepository(db),
        "affiliation": SqlAlchemyAffiliationRepository(db),
        "media": SqlAlchemyMediaRepository(db),
        "external_identifier": SqlAlchemyExternalIdentifierRepository(db),
        "outbox": SqlAlchemyOutboxRepository(db),
    }


def _identity_adapter(db: AsyncSession) -> IdentityAdapter:
    return IdentityAdapter(IdentityQueryService(SqlAlchemyUserRepository(db), SqlAlchemyRoleRepository(db)))


def get_completeness_service(db: DbSession) -> CompletenessService:
    r = _repos(db)
    return CompletenessService(
        r["registration"], r["qualification"], r["speciality"], r["language"], r["service"], r["media"], r["outbox"]
    )


def get_profile_service(db: DbSession) -> ProfileService:
    r = _repos(db)
    return ProfileService(r["provider"], get_completeness_service(db), r["outbox"])


def get_registration_service(db: DbSession) -> ProfessionalRegistrationService:
    r = _repos(db)
    return ProfessionalRegistrationService(r["registration"], get_completeness_service(db), r["outbox"])


def get_qualification_service(db: DbSession) -> QualificationService:
    r = _repos(db)
    return QualificationService(r["qualification"], r["speciality"], get_completeness_service(db), r["outbox"])


def get_speciality_service(db: DbSession) -> SpecialityService:
    r = _repos(db)
    return SpecialityService(r["speciality"], get_completeness_service(db), r["outbox"])


def get_language_service(db: DbSession) -> LanguageService:
    r = _repos(db)
    return LanguageService(r["language"], get_completeness_service(db), r["outbox"])


def get_service_offering_service(db: DbSession) -> ServiceOfferingService:
    r = _repos(db)
    return ServiceOfferingService(r["service"], r["speciality"], r["location"], get_completeness_service(db), r["outbox"])


def get_location_service(db: DbSession) -> LocationService:
    r = _repos(db)
    return LocationService(r["location"], r["service"], r["outbox"])


def get_affiliation_service(db: DbSession) -> AffiliationService:
    r = _repos(db)
    return AffiliationService(r["affiliation"], r["outbox"])


def get_media_service(db: DbSession) -> MediaService:
    r = _repos(db)
    return MediaService(r["media"], get_document_adapter(), r["outbox"])


def get_publication_service(db: DbSession) -> PublicationService:
    r = _repos(db)
    return PublicationService(
        r["provider"],
        r["registration"],
        r["qualification"],
        r["speciality"],
        r["language"],
        r["service"],
        get_completeness_service(db),
        _identity_adapter(db),
        r["outbox"],
    )


def get_provider_repo(db: DbSession):
    return _repos(db)["provider"]


def get_registration_repo(db: DbSession):
    return _repos(db)["registration"]


def get_qualification_repo(db: DbSession):
    return _repos(db)["qualification"]


def get_speciality_repo(db: DbSession):
    return _repos(db)["speciality"]


def get_language_repo(db: DbSession):
    return _repos(db)["language"]


def get_service_repo(db: DbSession):
    return _repos(db)["service"]


def get_location_repo(db: DbSession):
    return _repos(db)["location"]


def get_affiliation_repo(db: DbSession):
    return _repos(db)["affiliation"]


def get_media_repo(db: DbSession):
    return _repos(db)["media"]


__all__ = [
    "CurrentAuth",
    "DbSession",
    "flush_and_refresh",
    "get_affiliation_repo",
    "get_affiliation_service",
    "get_completeness_service",
    "get_language_repo",
    "get_language_service",
    "get_location_repo",
    "get_location_service",
    "get_media_repo",
    "get_media_service",
    "get_profile_service",
    "get_provider_repo",
    "get_publication_service",
    "get_qualification_repo",
    "get_qualification_service",
    "get_registration_repo",
    "get_registration_service",
    "get_service_offering_service",
    "get_service_repo",
    "get_speciality_repo",
    "get_speciality_service",
]
