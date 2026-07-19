"""SQLAlchemy implementations of the repository ports declared in
`domain/repositories.py`. Same conventions as
`app.modules.onboarding.infrastructure.repositories`.
"""

from __future__ import annotations

import datetime
import uuid

from sqlalchemy import delete, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.providers.domain.models import (
    EventOutbox,
    MedicalSpeciality,
    Provider,
    ProviderAffiliation,
    ProviderExternalIdentifier,
    ProviderLanguage,
    ProviderLocation,
    ProviderProfessionalRegistration,
    ProviderProfileMedia,
    ProviderPublicationHistory,
    ProviderQualification,
    ProviderService,
    ProviderServiceMode,
    ProviderSpeciality,
    ProviderStatusHistory,
    ProviderVisibilitySettings,
)

_SORT_COLUMNS = {
    "displayName": Provider.display_name,
    "createdAt": Provider.created_at,
}


class SqlAlchemyProviderRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, provider: Provider) -> None:
        self._session.add(provider)
        await self._session.flush()

    async def get_by_id(self, provider_id: uuid.UUID) -> Provider | None:
        stmt = select(Provider).where(Provider.id == provider_id, Provider.deleted_at.is_(None))
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def get_by_id_for_update(self, provider_id: uuid.UUID) -> Provider | None:
        stmt = (
            select(Provider)
            .where(Provider.id == provider_id, Provider.deleted_at.is_(None))
            .with_for_update()
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def get_by_user_id(self, user_id: uuid.UUID, provider_type: str | None = None) -> Provider | None:
        conditions = [Provider.user_id == user_id, Provider.deleted_at.is_(None)]
        if provider_type:
            conditions.append(Provider.provider_type == provider_type)
        stmt = select(Provider).where(*conditions).order_by(Provider.created_at.desc()).limit(1)
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def get_by_slug(self, slug: str) -> Provider | None:
        stmt = select(Provider).where(Provider.slug == slug, Provider.deleted_at.is_(None))
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def slug_exists(self, slug: str) -> bool:
        stmt = select(exists().where(Provider.slug == slug, Provider.deleted_at.is_(None)))
        return bool((await self._session.execute(stmt)).scalar_one())

    async def search(
        self,
        *,
        provider_type: str | None = None,
        verification_status: str | None = None,
        profile_status: str | None = None,
        publication_status: str | None = None,
        speciality_id: uuid.UUID | None = None,
        institution_id: uuid.UUID | None = None,
        registration_number: str | None = None,
        name: str | None = None,
        page: int = 0,
        size: int = 20,
        sort: str | None = None,
    ) -> tuple[list[Provider], int]:
        conditions = [Provider.deleted_at.is_(None)]
        if provider_type:
            conditions.append(Provider.provider_type == provider_type)
        if verification_status:
            conditions.append(Provider.verification_status == verification_status)
        if profile_status:
            conditions.append(Provider.profile_status == profile_status)
        if publication_status:
            conditions.append(Provider.publication_status == publication_status)
        if name:
            pattern = f"%{name}%"
            conditions.append(
                or_(Provider.display_name.ilike(pattern), Provider.first_name.ilike(pattern), Provider.last_name.ilike(pattern))
            )
        if speciality_id:
            conditions.append(
                exists().where(
                    ProviderSpeciality.provider_id == Provider.id,
                    ProviderSpeciality.speciality_id == speciality_id,
                    ProviderSpeciality.deleted_at.is_(None),
                )
            )
        if institution_id:
            conditions.append(
                exists().where(
                    ProviderAffiliation.provider_id == Provider.id,
                    ProviderAffiliation.institution_id == institution_id,
                )
            )
        if registration_number:
            conditions.append(
                exists().where(
                    ProviderProfessionalRegistration.provider_id == Provider.id,
                    ProviderProfessionalRegistration.registration_number == registration_number,
                    ProviderProfessionalRegistration.deleted_at.is_(None),
                )
            )

        count_stmt = select(func.count()).select_from(Provider).where(*conditions)
        total = (await self._session.execute(count_stmt)).scalar_one()

        field_name, _, direction = (sort or "createdAt,desc").partition(",")
        column = _SORT_COLUMNS.get(field_name, Provider.created_at)
        order = column.asc() if direction == "asc" else column.desc()

        stmt = select(Provider).where(*conditions).order_by(order).offset(page * size).limit(size)
        rows = list((await self._session.execute(stmt)).scalars().all())
        return rows, total

    async def add_status_history(self, entry: ProviderStatusHistory) -> None:
        self._session.add(entry)
        await self._session.flush()

    async def list_status_history(self, provider_id: uuid.UUID) -> list[ProviderStatusHistory]:
        stmt = (
            select(ProviderStatusHistory)
            .where(ProviderStatusHistory.provider_id == provider_id)
            .order_by(ProviderStatusHistory.created_at.desc())
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def add_publication_history(self, entry: ProviderPublicationHistory) -> None:
        self._session.add(entry)
        await self._session.flush()

    async def list_publication_history(self, provider_id: uuid.UUID) -> list[ProviderPublicationHistory]:
        stmt = (
            select(ProviderPublicationHistory)
            .where(ProviderPublicationHistory.provider_id == provider_id)
            .order_by(ProviderPublicationHistory.created_at.desc())
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def add_visibility_settings(self, settings: ProviderVisibilitySettings) -> None:
        self._session.add(settings)
        await self._session.flush()

    async def get_visibility_settings(self, provider_id: uuid.UUID) -> ProviderVisibilitySettings | None:
        stmt = select(ProviderVisibilitySettings).where(ProviderVisibilitySettings.provider_id == provider_id)
        return (await self._session.execute(stmt)).scalar_one_or_none()


class SqlAlchemyRegistrationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, registration: ProviderProfessionalRegistration) -> None:
        self._session.add(registration)
        await self._session.flush()

    async def get_by_id(self, registration_id: uuid.UUID) -> ProviderProfessionalRegistration | None:
        stmt = select(ProviderProfessionalRegistration).where(
            ProviderProfessionalRegistration.id == registration_id,
            ProviderProfessionalRegistration.deleted_at.is_(None),
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def list_for_provider(self, provider_id: uuid.UUID) -> list[ProviderProfessionalRegistration]:
        stmt = (
            select(ProviderProfessionalRegistration)
            .where(
                ProviderProfessionalRegistration.provider_id == provider_id,
                ProviderProfessionalRegistration.deleted_at.is_(None),
            )
            .order_by(ProviderProfessionalRegistration.created_at)
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def get_active_primary(self, provider_id: uuid.UUID) -> ProviderProfessionalRegistration | None:
        stmt = select(ProviderProfessionalRegistration).where(
            ProviderProfessionalRegistration.provider_id == provider_id,
            ProviderProfessionalRegistration.is_primary.is_(True),
            ProviderProfessionalRegistration.registration_status == "ACTIVE",
            ProviderProfessionalRegistration.deleted_at.is_(None),
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def find_by_reference(
        self, country: str, authority: str, number: str
    ) -> ProviderProfessionalRegistration | None:
        stmt = select(ProviderProfessionalRegistration).where(
            ProviderProfessionalRegistration.registration_country == country,
            ProviderProfessionalRegistration.registration_authority == authority,
            ProviderProfessionalRegistration.registration_number == number,
            ProviderProfessionalRegistration.deleted_at.is_(None),
            ProviderProfessionalRegistration.registration_status != "SUPERSEDED",
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def list_expiring(self, target_date: datetime.date) -> list[ProviderProfessionalRegistration]:
        stmt = select(ProviderProfessionalRegistration).where(
            ProviderProfessionalRegistration.expiry_date == target_date,
            ProviderProfessionalRegistration.registration_status == "ACTIVE",
            ProviderProfessionalRegistration.deleted_at.is_(None),
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def flush(self) -> None:
        await self._session.flush()


class SqlAlchemyQualificationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, qualification: ProviderQualification) -> None:
        self._session.add(qualification)
        await self._session.flush()

    async def get_by_id(self, qualification_id: uuid.UUID) -> ProviderQualification | None:
        stmt = select(ProviderQualification).where(
            ProviderQualification.id == qualification_id, ProviderQualification.deleted_at.is_(None)
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def list_for_provider(self, provider_id: uuid.UUID) -> list[ProviderQualification]:
        stmt = (
            select(ProviderQualification)
            .where(ProviderQualification.provider_id == provider_id, ProviderQualification.deleted_at.is_(None))
            .order_by(ProviderQualification.created_at)
        )
        return list((await self._session.execute(stmt)).scalars().all())


class SqlAlchemySpecialityRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_reference_by_id(self, speciality_id: uuid.UUID) -> MedicalSpeciality | None:
        stmt = select(MedicalSpeciality).where(MedicalSpeciality.id == speciality_id)
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def get_reference_by_code(self, code: str) -> MedicalSpeciality | None:
        stmt = select(MedicalSpeciality).where(MedicalSpeciality.code == code)
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def list_reference(
        self, *, provider_type: str | None = None, parent_code: str | None = None, active: bool | None = None
    ) -> list[MedicalSpeciality]:
        conditions = []
        if provider_type:
            conditions.append(MedicalSpeciality.provider_type == provider_type)
        if active is not None:
            conditions.append(MedicalSpeciality.active == active)
        if parent_code:
            parent = await self.get_reference_by_code(parent_code)
            conditions.append(MedicalSpeciality.parent_speciality_id == (parent.id if parent else None))
        stmt = select(MedicalSpeciality).where(*conditions).order_by(MedicalSpeciality.name)
        return list((await self._session.execute(stmt)).scalars().all())

    async def add_reference(self, speciality: MedicalSpeciality) -> None:
        self._session.add(speciality)
        await self._session.flush()

    async def add(self, assignment: ProviderSpeciality) -> None:
        self._session.add(assignment)
        await self._session.flush()

    async def get_by_id(self, provider_speciality_id: uuid.UUID) -> ProviderSpeciality | None:
        stmt = select(ProviderSpeciality).where(
            ProviderSpeciality.id == provider_speciality_id, ProviderSpeciality.deleted_at.is_(None)
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def list_for_provider(self, provider_id: uuid.UUID) -> list[ProviderSpeciality]:
        stmt = (
            select(ProviderSpeciality)
            .where(ProviderSpeciality.provider_id == provider_id, ProviderSpeciality.deleted_at.is_(None))
            .order_by(ProviderSpeciality.created_at)
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def get_primary(self, provider_id: uuid.UUID) -> ProviderSpeciality | None:
        stmt = select(ProviderSpeciality).where(
            ProviderSpeciality.provider_id == provider_id,
            ProviderSpeciality.is_primary.is_(True),
            ProviderSpeciality.deleted_at.is_(None),
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def get_assignment(self, provider_id: uuid.UUID, speciality_id: uuid.UUID) -> ProviderSpeciality | None:
        stmt = select(ProviderSpeciality).where(
            ProviderSpeciality.provider_id == provider_id,
            ProviderSpeciality.speciality_id == speciality_id,
            ProviderSpeciality.deleted_at.is_(None),
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def flush(self) -> None:
        await self._session.flush()


class SqlAlchemyLanguageRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, language: ProviderLanguage) -> None:
        self._session.add(language)
        await self._session.flush()

    async def get(self, provider_id: uuid.UUID, language_code: str) -> ProviderLanguage | None:
        stmt = select(ProviderLanguage).where(
            ProviderLanguage.provider_id == provider_id, ProviderLanguage.language_code == language_code
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def list_for_provider(self, provider_id: uuid.UUID) -> list[ProviderLanguage]:
        stmt = select(ProviderLanguage).where(ProviderLanguage.provider_id == provider_id).order_by(ProviderLanguage.created_at)
        return list((await self._session.execute(stmt)).scalars().all())

    async def delete(self, language: ProviderLanguage) -> None:
        await self._session.delete(language)
        await self._session.flush()


class SqlAlchemyServiceRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, service: ProviderService) -> None:
        self._session.add(service)
        await self._session.flush()

    async def get_by_id(self, service_id: uuid.UUID) -> ProviderService | None:
        stmt = select(ProviderService).where(ProviderService.id == service_id, ProviderService.deleted_at.is_(None))
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def list_for_provider(
        self,
        provider_id: uuid.UUID,
        *,
        status: str | None = None,
        delivery_mode: str | None = None,
        pro_bono: bool | None = None,
        speciality_id: uuid.UUID | None = None,
    ) -> list[ProviderService]:
        conditions = [ProviderService.provider_id == provider_id, ProviderService.deleted_at.is_(None)]
        if status:
            conditions.append(ProviderService.status == status)
        if pro_bono is not None:
            conditions.append(ProviderService.pro_bono == pro_bono)
        if speciality_id:
            conditions.append(ProviderService.speciality_id == speciality_id)
        if delivery_mode:
            conditions.append(
                exists().where(
                    ProviderServiceMode.provider_service_id == ProviderService.id,
                    ProviderServiceMode.delivery_mode == delivery_mode,
                )
            )
        stmt = select(ProviderService).where(*conditions).order_by(ProviderService.created_at)
        return list((await self._session.execute(stmt)).scalars().all())

    async def code_exists(self, provider_id: uuid.UUID, service_code: str, *, exclude_id: uuid.UUID | None = None) -> bool:
        conditions = [
            ProviderService.provider_id == provider_id,
            ProviderService.service_code == service_code,
            ProviderService.deleted_at.is_(None),
            ProviderService.status != "ARCHIVED",
        ]
        if exclude_id:
            conditions.append(ProviderService.id != exclude_id)
        stmt = select(exists().where(*conditions))
        return bool((await self._session.execute(stmt)).scalar_one())

    async def list_modes(self, service_id: uuid.UUID) -> list[str]:
        stmt = select(ProviderServiceMode.delivery_mode).where(ProviderServiceMode.provider_service_id == service_id)
        return list((await self._session.execute(stmt)).scalars().all())

    async def replace_modes(self, service_id: uuid.UUID, modes: list[str]) -> None:
        await self._session.execute(delete(ProviderServiceMode).where(ProviderServiceMode.provider_service_id == service_id))
        for mode in modes:
            self._session.add(ProviderServiceMode(provider_service_id=service_id, delivery_mode=mode))
        await self._session.flush()


class SqlAlchemyLocationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, location: ProviderLocation) -> None:
        self._session.add(location)
        await self._session.flush()

    async def get_by_id(self, location_id: uuid.UUID) -> ProviderLocation | None:
        stmt = select(ProviderLocation).where(ProviderLocation.id == location_id, ProviderLocation.deleted_at.is_(None))
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def list_for_provider(self, provider_id: uuid.UUID, *, active_only: bool = False) -> list[ProviderLocation]:
        conditions = [ProviderLocation.provider_id == provider_id, ProviderLocation.deleted_at.is_(None)]
        if active_only:
            conditions.append(ProviderLocation.active.is_(True))
        stmt = select(ProviderLocation).where(*conditions).order_by(ProviderLocation.created_at)
        return list((await self._session.execute(stmt)).scalars().all())

    async def get_primary(self, provider_id: uuid.UUID) -> ProviderLocation | None:
        stmt = select(ProviderLocation).where(
            ProviderLocation.provider_id == provider_id,
            ProviderLocation.is_primary.is_(True),
            ProviderLocation.active.is_(True),
            ProviderLocation.deleted_at.is_(None),
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def count_active_physical(self, provider_id: uuid.UUID) -> int:
        stmt = select(func.count()).select_from(ProviderLocation).where(
            ProviderLocation.provider_id == provider_id,
            ProviderLocation.active.is_(True),
            ProviderLocation.deleted_at.is_(None),
            ProviderLocation.location_type != "VIRTUAL",
        )
        return (await self._session.execute(stmt)).scalar_one()

    async def flush(self) -> None:
        await self._session.flush()


class SqlAlchemyAffiliationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, affiliation: ProviderAffiliation) -> None:
        self._session.add(affiliation)
        await self._session.flush()

    async def get_by_id(self, affiliation_id: uuid.UUID) -> ProviderAffiliation | None:
        stmt = select(ProviderAffiliation).where(ProviderAffiliation.id == affiliation_id)
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def list_for_provider(self, provider_id: uuid.UUID) -> list[ProviderAffiliation]:
        stmt = (
            select(ProviderAffiliation)
            .where(ProviderAffiliation.provider_id == provider_id)
            .order_by(ProviderAffiliation.created_at)
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def find_active(
        self, provider_id: uuid.UUID, institution_id: uuid.UUID, department_id: uuid.UUID | None, affiliation_type: str
    ) -> ProviderAffiliation | None:
        conditions = [
            ProviderAffiliation.provider_id == provider_id,
            ProviderAffiliation.institution_id == institution_id,
            ProviderAffiliation.affiliation_type == affiliation_type,
            ProviderAffiliation.status.in_(["PENDING", "ACTIVE"]),
        ]
        if department_id is not None:
            conditions.append(ProviderAffiliation.department_id == department_id)
        else:
            conditions.append(ProviderAffiliation.department_id.is_(None))
        stmt = select(ProviderAffiliation).where(*conditions)
        return (await self._session.execute(stmt)).scalar_one_or_none()


class SqlAlchemyMediaRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, media: ProviderProfileMedia) -> None:
        self._session.add(media)
        await self._session.flush()

    async def get_by_id(self, media_id: uuid.UUID) -> ProviderProfileMedia | None:
        stmt = select(ProviderProfileMedia).where(
            ProviderProfileMedia.id == media_id, ProviderProfileMedia.deleted_at.is_(None)
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def get_active(self, provider_id: uuid.UUID, media_type: str) -> ProviderProfileMedia | None:
        stmt = select(ProviderProfileMedia).where(
            ProviderProfileMedia.provider_id == provider_id,
            ProviderProfileMedia.media_type == media_type,
            ProviderProfileMedia.active.is_(True),
            ProviderProfileMedia.deleted_at.is_(None),
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def deactivate_others(self, provider_id: uuid.UUID, media_type: str, keep_id: uuid.UUID) -> None:
        stmt = select(ProviderProfileMedia).where(
            ProviderProfileMedia.provider_id == provider_id,
            ProviderProfileMedia.media_type == media_type,
            ProviderProfileMedia.active.is_(True),
            ProviderProfileMedia.id != keep_id,
        )
        others = list((await self._session.execute(stmt)).scalars().all())
        for media in others:
            media.active = False
        await self._session.flush()


class SqlAlchemyExternalIdentifierRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, identifier: ProviderExternalIdentifier) -> None:
        self._session.add(identifier)
        await self._session.flush()

    async def list_for_provider(self, provider_id: uuid.UUID) -> list[ProviderExternalIdentifier]:
        stmt = select(ProviderExternalIdentifier).where(ProviderExternalIdentifier.provider_id == provider_id)
        return list((await self._session.execute(stmt)).scalars().all())


class SqlAlchemyOutboxRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def enqueue(
        self,
        event_type: str,
        payload: dict,
        *,
        aggregate_id: uuid.UUID | None = None,
        aggregate_type: str = "Provider",
    ) -> None:
        self._session.add(
            EventOutbox(event_type=event_type, aggregate_type=aggregate_type, aggregate_id=aggregate_id, payload=payload)
        )
        await self._session.flush()
