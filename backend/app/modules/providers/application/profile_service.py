"""Provider profile lifecycle: creation (spec 8.1), self-service updates
and material-change detection (9.2), and the status-dimension transitions
driven by onboarding approval/suspension/reinstatement/expiry (7.1-7.5,
23.3-23.5, 34.1, 34.5). Cross-aggregate cascades (marking registrations
verified, suspending active services) are deliberately NOT done here —
they're orchestrated by `infrastructure/provider_port_adapter.py`, which
composes this service with `professional_registration_service.py`,
`qualification_service.py`, and `service_offering_service.py`. This
service only ever touches `providers`/`provider_status_history`/
`provider_publication_history`/`provider_visibility_settings`.
"""

from __future__ import annotations

import datetime
import uuid

from app.modules.providers.application.completeness_service import CompletenessService
from app.modules.providers.domain.enums import ProviderType
from app.modules.providers.domain.events import ProviderEvent
from app.modules.providers.domain.exceptions import ProviderError
from app.modules.providers.domain.models import (
    Provider,
    ProviderPublicationHistory,
    ProviderStatusHistory,
    ProviderVisibilitySettings,
)
from app.modules.providers.domain.repositories import OutboxRepository, ProviderRepository
from app.modules.providers.domain.rules import PROFILE_MATERIAL_FIELDS, detect_material_change
from app.modules.providers.infrastructure.slug import generate_unique_slug

_EDITABLE_SELF_FIELDS = {
    "first_name",
    "middle_name",
    "last_name",
    "professional_title",
    "display_name",
    "short_biography",
    "biography",
    "date_of_birth",
    "gender",
    "nationality",
    "years_of_experience",
}

_VERIFIED_STATUSES = {"VERIFIED", "CONDITIONALLY_VERIFIED"}


class ProfileService:
    def __init__(
        self,
        provider_repo: ProviderRepository,
        completeness_service: CompletenessService,
        outbox_repo: OutboxRepository,
    ) -> None:
        self._providers = provider_repo
        self._completeness = completeness_service
        self._outbox = outbox_repo

    # --- Creation (spec 8.1, 8.2, 34.1) --------------------------------------

    async def create_provider(
        self,
        *,
        user_id: uuid.UUID,
        provider_type: str,
        first_name: str,
        last_name: str,
    ) -> Provider:
        if provider_type not in {t.value for t in ProviderType}:
            raise ProviderError.for_code("PROVIDER_TYPE_INVALID")

        existing = await self._providers.get_by_user_id(user_id, provider_type)
        if existing is not None:
            return existing  # spec 8.2 — idempotent, no duplicate

        slug = await generate_unique_slug(self._providers, first_name, last_name)

        provider = Provider(
            user_id=user_id,
            provider_type=provider_type,
            first_name=first_name,
            last_name=last_name,
            display_name=f"{first_name} {last_name}",
            slug=slug,
            verification_status="NOT_VERIFIED",
            profile_status="DRAFT",
            publication_status="UNPUBLISHED",
        )
        await self._providers.add(provider)

        await self._providers.add_visibility_settings(ProviderVisibilitySettings(provider_id=provider.id))

        for status_type, new_status in (
            ("VERIFICATION_STATUS", "NOT_VERIFIED"),
            ("PROFILE_STATUS", "DRAFT"),
            ("PUBLICATION_STATUS", "UNPUBLISHED"),
        ):
            await self._write_status_history(provider, status_type, None, new_status, source_type="REGISTRATION")

        await self._completeness.refresh(provider)

        await self._outbox.enqueue(
            ProviderEvent.CREATED,
            {"providerId": str(provider.id), "userId": str(user_id), "providerType": provider_type, "slug": slug},
            aggregate_id=provider.id,
        )
        return provider

    # --- Queries --------------------------------------------------------------

    async def get_provider(self, provider_id: uuid.UUID) -> Provider:
        provider = await self._providers.get_by_id(provider_id)
        if provider is None:
            raise ProviderError.for_code("PROVIDER_NOT_FOUND")
        return provider

    async def get_by_user_id(self, user_id: uuid.UUID, provider_type: str | None = None) -> Provider | None:
        return await self._providers.get_by_user_id(user_id, provider_type)

    async def require_by_user_id(self, user_id: uuid.UUID, provider_type: str | None = None) -> Provider:
        provider = await self._providers.get_by_user_id(user_id, provider_type)
        if provider is None:
            raise ProviderError.for_code("PROVIDER_NOT_FOUND")
        return provider

    # --- Self-service update (spec 9.2) ----------------------------------------

    async def update_profile(
        self, provider: Provider, *, updates: dict, expected_version: int, reason: str | None = None
    ) -> tuple[Provider, bool]:
        if provider.version != expected_version:
            raise ProviderError.for_code("PROVIDER_PROFILE_VERSION_CONFLICT")

        changed_fields: set[str] = set()
        for field, value in updates.items():
            if field not in _EDITABLE_SELF_FIELDS:
                continue
            if getattr(provider, field) != value:
                setattr(provider, field, value)
                changed_fields.add(field)

        if not changed_fields:
            return provider, False

        await self._completeness.refresh(provider)

        material_change = detect_material_change(changed_fields) and provider.verification_status in _VERIFIED_STATUSES
        if material_change:
            await self._outbox.enqueue(
                ProviderEvent.MATERIAL_CHANGE_DETECTED,
                {
                    "providerId": str(provider.id),
                    "changedFields": sorted(changed_fields & PROFILE_MATERIAL_FIELDS),
                },
                aggregate_id=provider.id,
            )

        payload = {"providerId": str(provider.id), "changedFields": sorted(changed_fields)}
        if reason:
            payload["reason"] = reason
        await self._outbox.enqueue(ProviderEvent.PROFILE_UPDATED, payload, aggregate_id=provider.id)
        return provider, material_change

    # --- Status transitions (spec 7, 23.3-23.5, 34.5) --------------------------

    async def activate_provider(
        self,
        provider: Provider,
        *,
        approval_reference: str,
        approval_valid_until: datetime.datetime | None,
        source_reference: str | None,
        changed_by: uuid.UUID | None,
    ) -> None:
        if provider.verification_status == "VERIFIED" and provider.profile_status == "ACTIVE":
            return  # already applied — idempotent under outbox retry

        prev_verification, prev_profile = provider.verification_status, provider.profile_status
        provider.verification_status = "VERIFIED"
        provider.profile_status = "ACTIVE"
        provider.approval_reference = approval_reference
        provider.approval_valid_until = approval_valid_until
        now = datetime.datetime.now(datetime.UTC)
        provider.verified_at = now
        provider.activated_at = now

        await self._write_status_history(
            provider, "VERIFICATION_STATUS", prev_verification, "VERIFIED",
            source_type="ONBOARDING_APPROVAL", source_reference=source_reference, changed_by=changed_by,
        )
        await self._write_status_history(
            provider, "PROFILE_STATUS", prev_profile, "ACTIVE",
            source_type="ONBOARDING_APPROVAL", source_reference=source_reference, changed_by=changed_by,
        )
        await self._completeness.refresh(provider)

        await self._outbox.enqueue(
            ProviderEvent.ACTIVATED,
            {"providerId": str(provider.id), "approvalReference": approval_reference},
            aggregate_id=provider.id,
        )

    async def conditionally_activate_provider(
        self,
        provider: Provider,
        *,
        approval_reference: str,
        approval_valid_until: datetime.datetime | None,
        conditions: list[dict] | None,
        source_reference: str | None,
        changed_by: uuid.UUID | None,
    ) -> None:
        if provider.verification_status == "CONDITIONALLY_VERIFIED" and provider.profile_status == "ACTIVE":
            return

        prev_verification, prev_profile = provider.verification_status, provider.profile_status
        provider.verification_status = "CONDITIONALLY_VERIFIED"
        provider.profile_status = "ACTIVE"
        provider.approval_reference = approval_reference
        provider.approval_valid_until = approval_valid_until
        now = datetime.datetime.now(datetime.UTC)
        provider.verified_at = now
        provider.activated_at = now

        await self._write_status_history(
            provider, "VERIFICATION_STATUS", prev_verification, "CONDITIONALLY_VERIFIED",
            source_type="ONBOARDING_APPROVAL", source_reference=source_reference, changed_by=changed_by,
            comments=f"conditions={conditions}" if conditions else None,
        )
        await self._write_status_history(
            provider, "PROFILE_STATUS", prev_profile, "ACTIVE",
            source_type="ONBOARDING_APPROVAL", source_reference=source_reference, changed_by=changed_by,
        )
        await self._completeness.refresh(provider)

        await self._outbox.enqueue(
            ProviderEvent.CONDITIONALLY_ACTIVATED,
            {"providerId": str(provider.id), "approvalReference": approval_reference, "conditions": conditions or []},
            aggregate_id=provider.id,
        )

    async def suspend_provider(
        self,
        provider: Provider,
        *,
        reason_code: str,
        comments: str | None,
        source_type: str,
        source_reference: str | None,
        changed_by: uuid.UUID | None,
    ) -> None:
        if provider.profile_status == "SUSPENDED":
            return  # already applied

        prev_verification, prev_profile, prev_publication = (
            provider.verification_status,
            provider.profile_status,
            provider.publication_status,
        )
        provider.verification_status = "SUSPENDED"
        provider.profile_status = "SUSPENDED"
        provider.publication_status = "HIDDEN"
        provider.suspended_at = datetime.datetime.now(datetime.UTC)

        await self._write_status_history(
            provider, "VERIFICATION_STATUS", prev_verification, "SUSPENDED",
            reason_code=reason_code, comments=comments, source_type=source_type,
            source_reference=source_reference, changed_by=changed_by,
        )
        await self._write_status_history(
            provider, "PROFILE_STATUS", prev_profile, "SUSPENDED",
            reason_code=reason_code, comments=comments, source_type=source_type,
            source_reference=source_reference, changed_by=changed_by,
        )
        if prev_publication != "HIDDEN":
            await self._write_status_history(
                provider, "PUBLICATION_STATUS", prev_publication, "HIDDEN",
                reason_code=reason_code, comments=comments, source_type=source_type,
                source_reference=source_reference, changed_by=changed_by,
            )
            await self._record_publication_history(provider, "HIDDEN", reason_code=reason_code, comments=comments, performed_by=changed_by)

        await self._outbox.enqueue(
            ProviderEvent.SUSPENDED,
            {"providerId": str(provider.id), "reasonCode": reason_code},
            aggregate_id=provider.id,
        )

    async def reinstate_provider(
        self,
        provider: Provider,
        *,
        approval_reference: str | None,
        source_reference: str | None,
        changed_by: uuid.UUID | None,
    ) -> None:
        if provider.profile_status == "ACTIVE" and provider.verification_status == "VERIFIED":
            return  # already applied

        prev_verification, prev_profile = provider.verification_status, provider.profile_status
        provider.verification_status = "VERIFIED"
        provider.profile_status = "ACTIVE"
        if approval_reference:
            provider.approval_reference = approval_reference
        provider.suspended_at = None

        await self._write_status_history(
            provider, "VERIFICATION_STATUS", prev_verification, "VERIFIED",
            source_type="ONBOARDING_REINSTATEMENT", source_reference=source_reference, changed_by=changed_by,
        )
        await self._write_status_history(
            provider, "PROFILE_STATUS", prev_profile, "ACTIVE",
            source_type="ONBOARDING_REINSTATEMENT", source_reference=source_reference, changed_by=changed_by,
        )
        await self._completeness.refresh(provider)

        # Reinstatement doesn't automatically re-publish (spec 37.11:
        # "not automatically published unless publication criteria are
        # met") — publication_status is left untouched here; a provider
        # who wants to be public again goes through the normal
        # POST .../publication/publish flow, which re-validates eligibility.

        await self._outbox.enqueue(
            ProviderEvent.REINSTATED,
            {"providerId": str(provider.id)},
            aggregate_id=provider.id,
        )

    async def expire_provider(self, provider: Provider, *, target_profile_status: str = "INACTIVE") -> None:
        """Spec 7.5 — mandatory credential expiry. `target_profile_status`
        defaults to INACTIVE (spec: "should be configurable according to
        regulation and operating policy"); callers may pass SUSPENDED.
        """
        if provider.verification_status == "EXPIRED":
            return

        prev_verification, prev_profile, prev_publication = (
            provider.verification_status,
            provider.profile_status,
            provider.publication_status,
        )
        provider.verification_status = "EXPIRED"
        provider.profile_status = target_profile_status
        provider.publication_status = "HIDDEN"

        await self._write_status_history(provider, "VERIFICATION_STATUS", prev_verification, "EXPIRED", source_type="CREDENTIAL_EXPIRY")
        if prev_profile != target_profile_status:
            await self._write_status_history(provider, "PROFILE_STATUS", prev_profile, target_profile_status, source_type="CREDENTIAL_EXPIRY")
        if prev_publication != "HIDDEN":
            await self._write_status_history(provider, "PUBLICATION_STATUS", prev_publication, "HIDDEN", source_type="CREDENTIAL_EXPIRY")
            await self._record_publication_history(provider, "HIDDEN", reason_code="CREDENTIAL_EXPIRED", comments=None, performed_by=None)

    # --- Publication history / hide (spec 19.4) ----------------------------------

    async def hide_provider(self, provider: Provider, *, reason_code: str, comments: str | None, changed_by: uuid.UUID | None) -> None:
        """Administrative hide (spec 19.4) — publication only, does not
        revoke professional approval (verification/profile status untouched).
        """
        if provider.publication_status == "HIDDEN":
            raise ProviderError.for_code("PROVIDER_NOT_PUBLISHED", "The provider profile is already hidden.")

        prev_publication = provider.publication_status
        provider.publication_status = "HIDDEN"

        await self._write_status_history(
            provider, "PUBLICATION_STATUS", prev_publication, "HIDDEN",
            reason_code=reason_code, comments=comments, source_type="BACK_OFFICE", changed_by=changed_by,
        )
        await self._record_publication_history(provider, "HIDDEN", reason_code=reason_code, comments=comments, performed_by=changed_by)

        await self._outbox.enqueue(
            ProviderEvent.HIDDEN,
            {"providerId": str(provider.id), "reasonCode": reason_code},
            aggregate_id=provider.id,
        )

    # --- Shared helpers -----------------------------------------------------------

    async def _write_status_history(
        self,
        provider: Provider,
        status_type: str,
        previous_status: str | None,
        new_status: str,
        *,
        reason_code: str | None = None,
        comments: str | None = None,
        source_type: str | None = None,
        source_reference: str | None = None,
        changed_by: uuid.UUID | None = None,
    ) -> None:
        await self._providers.add_status_history(
            ProviderStatusHistory(
                provider_id=provider.id,
                status_type=status_type,
                previous_status=previous_status,
                new_status=new_status,
                reason_code=reason_code,
                comments=comments,
                source_type=source_type,
                source_reference=source_reference,
                changed_by=changed_by,
            )
        )

    async def _record_publication_history(
        self, provider: Provider, action: str, *, reason_code: str | None, comments: str | None, performed_by: uuid.UUID | None
    ) -> None:
        await self._providers.add_publication_history(
            ProviderPublicationHistory(
                provider_id=provider.id,
                action=action,
                reason_code=reason_code,
                comments=comments,
                performed_by=performed_by,
            )
        )
