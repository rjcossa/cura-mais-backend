"""Institution affiliation management (spec section 17, 33.7, 37.9).

Institution existence/active-status checking (spec 17's "the institution
must exist and be active") is deliberately not enforced against
`app.shared.institution.port` here: that port's mock only reports an
institution "active" once Onboarding has approved a HOSPITAL/CLINIC/
PHARMACY application for that exact institution id, which would make
every Providers-side affiliation test hostage to driving a full
institution-onboarding flow first, for a module that (like Providers
itself, from Onboarding's point of view) doesn't really exist yet either.
`institution_id`/`department_id` are accepted as logical references only
(spec 2.3), matching "Institution data should not be duplicated beyond
the minimum information required."

Confirming/rejecting is exposed as a back-office-permissioned action
(`PROVIDER_AFFILIATION_CONFIRM`/`PROVIDER_AFFILIATION_REJECT`) standing in
for "the Institution module calls confirmAffiliation(...)" (spec 17.7),
the same way a human back-office reviewer already stands in for a missing
external registry via `ManualRegistryAdapter` in Onboarding.
"""

from __future__ import annotations

import datetime
import uuid

from app.modules.providers.domain.enums import AffiliationType
from app.modules.providers.domain.events import ProviderEvent
from app.modules.providers.domain.exceptions import ProviderError
from app.modules.providers.domain.models import Provider, ProviderAffiliation
from app.modules.providers.domain.repositories import AffiliationRepository, OutboxRepository


class AffiliationService:
    def __init__(self, affiliation_repo: AffiliationRepository, outbox_repo: OutboxRepository) -> None:
        self._affiliations = affiliation_repo
        self._outbox = outbox_repo

    async def list_for_provider(self, provider_id: uuid.UUID) -> list[ProviderAffiliation]:
        return await self._affiliations.list_for_provider(provider_id)

    async def get_owned(self, provider_id: uuid.UUID, affiliation_id: uuid.UUID) -> ProviderAffiliation:
        affiliation = await self._affiliations.get_by_id(affiliation_id)
        if affiliation is None or affiliation.provider_id != provider_id:
            raise ProviderError.for_code("PROVIDER_AFFILIATION_NOT_FOUND")
        return affiliation

    async def get_any(self, affiliation_id: uuid.UUID) -> ProviderAffiliation:
        affiliation = await self._affiliations.get_by_id(affiliation_id)
        if affiliation is None:
            raise ProviderError.for_code("PROVIDER_AFFILIATION_NOT_FOUND")
        return affiliation

    async def request_affiliation(
        self,
        provider: Provider,
        *,
        institution_id: uuid.UUID,
        department_id: uuid.UUID | None,
        affiliation_type: str,
        professional_position: str | None,
        start_date: datetime.date | None,
        end_date: datetime.date | None,
        requested_by: uuid.UUID | None,
    ) -> ProviderAffiliation:
        if affiliation_type not in {t.value for t in AffiliationType}:
            raise ProviderError.for_code("PROVIDER_AFFILIATION_STATE_INVALID", "Unsupported affiliation type.")
        if end_date and start_date and end_date < start_date:
            raise ProviderError.for_code("PROVIDER_AFFILIATION_STATE_INVALID", "End date cannot precede the start date.")

        existing = await self._affiliations.find_active(provider.id, institution_id, department_id, affiliation_type)
        if existing is not None:
            raise ProviderError.for_code("PROVIDER_AFFILIATION_ALREADY_EXISTS")

        affiliation = ProviderAffiliation(
            provider_id=provider.id,
            institution_id=institution_id,
            department_id=department_id,
            affiliation_type=affiliation_type,
            affiliation_source="SELF_DECLARED",
            professional_position=professional_position,
            start_date=start_date,
            end_date=end_date,
            status="PENDING",
            requested_by=requested_by,
        )
        await self._affiliations.add(affiliation)

        await self._outbox.enqueue(
            ProviderEvent.AFFILIATION_REQUESTED,
            {"providerId": str(provider.id), "affiliationId": str(affiliation.id), "institutionId": str(institution_id)},
            aggregate_id=provider.id,
        )
        return affiliation

    async def update_affiliation(self, affiliation: ProviderAffiliation, *, updates: dict) -> ProviderAffiliation:
        for field, value in updates.items():
            if hasattr(affiliation, field):
                setattr(affiliation, field, value)
        return affiliation

    async def confirm(self, affiliation: ProviderAffiliation, *, confirmed_by: uuid.UUID | None) -> ProviderAffiliation:
        if affiliation.status != "PENDING":
            raise ProviderError.for_code("PROVIDER_AFFILIATION_STATE_INVALID")
        affiliation.status = "ACTIVE"
        affiliation.confirmed_by = confirmed_by
        affiliation.confirmed_at = datetime.datetime.now(datetime.UTC)

        await self._outbox.enqueue(
            ProviderEvent.AFFILIATION_CONFIRMED,
            {"providerId": str(affiliation.provider_id), "affiliationId": str(affiliation.id)},
            aggregate_id=affiliation.provider_id,
        )
        return affiliation

    async def reject(self, affiliation: ProviderAffiliation, *, reason: str) -> ProviderAffiliation:
        if affiliation.status != "PENDING":
            raise ProviderError.for_code("PROVIDER_AFFILIATION_STATE_INVALID")
        affiliation.status = "REJECTED"
        affiliation.rejection_reason = reason

        await self._outbox.enqueue(
            ProviderEvent.AFFILIATION_REJECTED,
            {"providerId": str(affiliation.provider_id), "affiliationId": str(affiliation.id), "reason": reason},
            aggregate_id=affiliation.provider_id,
        )
        return affiliation

    async def end_affiliation(
        self, affiliation: ProviderAffiliation, *, end_date: datetime.date, reason: str | None
    ) -> ProviderAffiliation:
        if affiliation.status not in ("ACTIVE", "PENDING", "SUSPENDED"):
            raise ProviderError.for_code("PROVIDER_AFFILIATION_STATE_INVALID")
        affiliation.status = "ENDED"
        affiliation.end_date = end_date
        affiliation.ended_reason = reason

        await self._outbox.enqueue(
            ProviderEvent.AFFILIATION_ENDED,
            {"providerId": str(affiliation.provider_id), "affiliationId": str(affiliation.id)},
            aggregate_id=affiliation.provider_id,
        )
        return affiliation
