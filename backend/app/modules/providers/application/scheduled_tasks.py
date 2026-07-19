"""Periodic processing — registration-expiry monitoring (spec section 36).

Mirrors `app.modules.onboarding.application.scheduled_tasks`'s loop
structure exactly (one background asyncio loop, hourly by default, same
"schema not migrated yet" tolerance), including its full 5-tier reminder
cadence (90/60/30/7/on-expiry) — implementing all 5 costs the same as one
under this loop-based idiom, so there's no reason to trim it.

Unlike that onboarding job, this one *does* dedupe: `list_expiring`
matches on `expiry_date == target_date`, and an hourly poll would
otherwise re-enqueue the same reminder on every tick for the rest of that
calendar day (confirmed this gap exists in the onboarding original by
reading it — not fixed there, since that's pre-existing shipped
behaviour outside this module's boundary, but not worth repeating in new
code). `last_expiry_reminder_window_days` (not in spec 30.2's DDL) is the
dedup marker.
"""

from __future__ import annotations

import asyncio
import datetime
import logging

from sqlalchemy.exc import DBAPIError

from app.core.database import get_session_factory
from app.modules.providers.domain.enums import VerificationStatus
from app.modules.providers.domain.events import ProviderEvent, ProviderNotification
from app.modules.providers.domain.models import Provider, ProviderStatusHistory
from app.modules.providers.infrastructure.repositories import (
    SqlAlchemyOutboxRepository,
    SqlAlchemyProviderRepository,
    SqlAlchemyRegistrationRepository,
)

logger = logging.getLogger(__name__)

_UNDEFINED_TABLE_SQLSTATE = "42P01"
_EXPIRY_REMINDER_WINDOWS_DAYS = (90, 60, 30, 7, 0)
_TERMINAL_VERIFICATION_STATUSES = {
    VerificationStatus.EXPIRED.value,
    VerificationStatus.SUSPENDED.value,
    VerificationStatus.REVOKED.value,
}


async def run_once() -> None:
    session_factory = get_session_factory()
    async with session_factory() as session:
        try:
            await _process_expiring_registrations(session)
            await session.commit()
        except DBAPIError as exc:
            if getattr(exc.orig, "sqlstate", None) == _UNDEFINED_TABLE_SQLSTATE:
                await session.rollback()
                return  # Schema not migrated yet — same tolerance as the outbox dispatcher.
            raise


async def _process_expiring_registrations(session) -> None:
    registrations = SqlAlchemyRegistrationRepository(session)
    providers = SqlAlchemyProviderRepository(session)
    outbox = SqlAlchemyOutboxRepository(session)
    today = datetime.date.today()

    for window_days in _EXPIRY_REMINDER_WINDOWS_DAYS:
        target_date = today + datetime.timedelta(days=window_days)
        for registration in await registrations.list_expiring(target_date):
            if registration.last_expiry_reminder_window_days == window_days:
                continue  # already sent this tier's reminder — see module docstring
            registration.last_expiry_reminder_window_days = window_days

            is_expiry = window_days == 0
            event_type = ProviderEvent.REGISTRATION_EXPIRED if is_expiry else ProviderEvent.REGISTRATION_EXPIRING
            notification = (
                ProviderNotification.REGISTRATION_EXPIRED if is_expiry else ProviderNotification.REGISTRATION_EXPIRING
            )
            await outbox.enqueue(
                event_type,
                {
                    "providerId": str(registration.provider_id),
                    "registrationId": str(registration.id),
                    "daysUntilExpiry": window_days,
                    "notificationCommand": notification,
                    "channel": "EMAIL",
                },
                aggregate_id=registration.provider_id,
            )

            if is_expiry:
                registration.registration_status = "EXPIRED"
                if registration.is_primary:
                    provider = await providers.get_by_id(registration.provider_id)
                    if provider is not None and provider.verification_status not in _TERMINAL_VERIFICATION_STATUSES:
                        await _apply_provider_expiry(provider, providers, outbox)


async def _apply_provider_expiry(provider: Provider, providers: SqlAlchemyProviderRepository, outbox: SqlAlchemyOutboxRepository) -> None:
    """Spec 7.5. Writes status history directly rather than going through
    `ProfileService.expire_provider` — that would need its full
    dependency graph (a completeness service + 5 repositories) built just
    for this one transition, when this job already holds everything it
    needs via the same session.
    """
    prev_verification, prev_profile, prev_publication = (
        provider.verification_status,
        provider.profile_status,
        provider.publication_status,
    )
    provider.verification_status = "EXPIRED"
    provider.profile_status = "INACTIVE"
    provider.publication_status = "HIDDEN"

    for status_type, previous, new in (
        ("VERIFICATION_STATUS", prev_verification, "EXPIRED"),
        ("PROFILE_STATUS", prev_profile, "INACTIVE"),
        ("PUBLICATION_STATUS", prev_publication, "HIDDEN"),
    ):
        if previous != new:
            await providers.add_status_history(
                ProviderStatusHistory(
                    provider_id=provider.id,
                    status_type=status_type,
                    previous_status=previous,
                    new_status=new,
                    reason_code="PRIMARY_REGISTRATION_EXPIRED",
                    source_type="CREDENTIAL_EXPIRY",
                )
            )

    await outbox.enqueue(
        ProviderEvent.REGISTRATION_EXPIRED,
        {"providerId": str(provider.id), "reasonCode": "PRIMARY_REGISTRATION_EXPIRED"},
        aggregate_id=provider.id,
    )


async def run_polling_loop(interval_seconds: float = 3600.0, stop_event: asyncio.Event | None = None) -> None:
    logger.info("Providers scheduled-task loop started (interval=%.0fs)", interval_seconds)
    while stop_event is None or not stop_event.is_set():
        try:
            await run_once()
        except Exception:  # noqa: BLE001 - never let the loop die
            logger.exception("Providers scheduled task run failed")
        try:
            if stop_event is not None:
                await asyncio.wait_for(stop_event.wait(), timeout=interval_seconds)
            else:
                await asyncio.sleep(interval_seconds)
        except TimeoutError:
            pass
