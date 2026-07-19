"""Qualification management (spec section 11, 33.3, 37.4)."""

from __future__ import annotations

import datetime
import uuid

from app.modules.providers.application.completeness_service import CompletenessService
from app.modules.providers.domain.enums import QualificationType
from app.modules.providers.domain.events import ProviderEvent
from app.modules.providers.domain.exceptions import ProviderError
from app.modules.providers.domain.models import Provider, ProviderQualification
from app.modules.providers.domain.repositories import OutboxRepository, QualificationRepository, SpecialityRepository

_MATERIAL_QUALIFICATION_FIELDS = {"qualification_type", "qualification_name", "institution_name", "institution_country"}


class QualificationService:
    def __init__(
        self,
        qualification_repo: QualificationRepository,
        speciality_repo: SpecialityRepository,
        completeness_service: CompletenessService,
        outbox_repo: OutboxRepository,
    ) -> None:
        self._qualifications = qualification_repo
        self._specialities = speciality_repo
        self._completeness = completeness_service
        self._outbox = outbox_repo

    async def list_for_provider(self, provider_id: uuid.UUID) -> list[ProviderQualification]:
        return await self._qualifications.list_for_provider(provider_id)

    async def get_owned(self, provider_id: uuid.UUID, qualification_id: uuid.UUID) -> ProviderQualification:
        qualification = await self._qualifications.get_by_id(qualification_id)
        if qualification is None or qualification.provider_id != provider_id:
            raise ProviderError.for_code("PROVIDER_QUALIFICATION_NOT_FOUND")
        return qualification

    async def add_qualification(
        self,
        provider: Provider,
        *,
        qualification_type: str,
        qualification_name: str,
        institution_name: str,
        institution_country: str | None,
        start_date: datetime.date | None,
        completion_date: datetime.date | None,
        speciality_id: uuid.UUID | None,
    ) -> ProviderQualification:
        if qualification_type not in {t.value for t in QualificationType}:
            raise ProviderError.for_code("PROVIDER_QUALIFICATION_INVALID", "Unsupported qualification type.")
        self._validate_dates(start_date, completion_date)
        if speciality_id is not None and await self._specialities.get_reference_by_id(speciality_id) is None:
            raise ProviderError.for_code("PROVIDER_SPECIALITY_NOT_FOUND")

        qualification = ProviderQualification(
            provider_id=provider.id,
            qualification_type=qualification_type,
            qualification_name=qualification_name,
            institution_name=institution_name,
            institution_country=institution_country,
            start_date=start_date,
            completion_date=completion_date,
            speciality_id=speciality_id,
            verification_status="UNVERIFIED",
        )
        await self._qualifications.add(qualification)
        await self._completeness.refresh(provider)

        await self._outbox.enqueue(
            ProviderEvent.QUALIFICATION_ADDED,
            {"providerId": str(provider.id), "qualificationId": str(qualification.id)},
            aggregate_id=provider.id,
        )
        return qualification

    async def update_qualification(
        self, provider: Provider, qualification: ProviderQualification, *, updates: dict
    ) -> ProviderQualification:
        if qualification.decision_locked:
            raise ProviderError.for_code("PROVIDER_QUALIFICATION_LOCKED")

        changed = {f for f, v in updates.items() if hasattr(qualification, f) and getattr(qualification, f) != v}
        if not changed:
            return qualification

        if qualification.verification_status == "VERIFIED" and (changed & _MATERIAL_QUALIFICATION_FIELDS):
            return await self._supersede(provider, qualification, updates)

        for field, value in updates.items():
            if hasattr(qualification, field):
                setattr(qualification, field, value)
        self._validate_dates(qualification.start_date, qualification.completion_date)

        await self._completeness.refresh(provider)
        return qualification

    async def _supersede(
        self, provider: Provider, old: ProviderQualification, updates: dict
    ) -> ProviderQualification:
        new = ProviderQualification(
            provider_id=provider.id,
            qualification_type=updates.get("qualification_type", old.qualification_type),
            qualification_name=updates.get("qualification_name", old.qualification_name),
            institution_name=updates.get("institution_name", old.institution_name),
            institution_country=updates.get("institution_country", old.institution_country),
            start_date=updates.get("start_date", old.start_date),
            completion_date=updates.get("completion_date", old.completion_date),
            speciality_id=updates.get("speciality_id", old.speciality_id),
            verification_status="UNVERIFIED",
            supersedes_qualification_id=old.id,
        )
        self._validate_dates(new.start_date, new.completion_date)

        old.deleted_at = datetime.datetime.now(datetime.UTC)
        await self._qualifications.add(new)
        await self._completeness.refresh(provider)

        await self._outbox.enqueue(
            ProviderEvent.QUALIFICATION_ADDED,
            {"providerId": str(provider.id), "qualificationId": str(new.id), "supersedesQualificationId": str(old.id)},
            aggregate_id=provider.id,
        )
        return new

    async def delete_qualification(self, provider: Provider, qualification: ProviderQualification) -> None:
        if qualification.decision_locked:
            raise ProviderError.for_code("PROVIDER_QUALIFICATION_LOCKED")
        if qualification.verification_status != "UNVERIFIED":
            raise ProviderError.for_code(
                "PROVIDER_QUALIFICATION_LOCKED",
                "Verified qualifications cannot be deleted — supersede them instead.",
            )
        qualification.deleted_at = datetime.datetime.now(datetime.UTC)
        await self._completeness.refresh(provider)

    async def mark_all_verified(self, provider_id: uuid.UUID, *, verified_by: uuid.UUID | None) -> None:
        """Spec 23.3 step 8."""
        now = datetime.datetime.now(datetime.UTC)
        for qualification in await self._qualifications.list_for_provider(provider_id):
            if qualification.verification_status in ("UNVERIFIED", "PENDING"):
                qualification.verification_status = "VERIFIED"
                qualification.verified_at = now
                qualification.verified_by = verified_by

    @staticmethod
    def _validate_dates(start_date: datetime.date | None, completion_date: datetime.date | None) -> None:
        if start_date and completion_date and completion_date < start_date:
            raise ProviderError.for_code("PROVIDER_QUALIFICATION_INVALID", "Completion date cannot precede the start date.")
