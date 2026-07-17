"""Periodic processing (spec sections 15.3 overdue information requests,
18.1 credential expiry monitoring).

No real job scheduler (cron/celery-beat) is wired up for this stage — in
production this logic would run there instead. For a locally-runnable
module today, it's a background asyncio loop started from `app.main`'s
lifespan, exactly like the outbox dispatcher, just on a much longer
interval (default: once per hour) since these are day-granularity
concerns, not second-granularity ones.
"""

from __future__ import annotations

import asyncio
import datetime
import logging

from sqlalchemy import select
from sqlalchemy.exc import DBAPIError

from app.core.database import get_session_factory
from app.modules.onboarding.domain.events import OnboardingEvent, OnboardingNotification
from app.modules.onboarding.domain.models import OnboardingApplicationDocument
from app.modules.onboarding.infrastructure.repositories import (
    SqlAlchemyInformationRequestRepository,
    SqlAlchemyOutboxRepository,
)

logger = logging.getLogger(__name__)

_UNDEFINED_TABLE_SQLSTATE = "42P01"
_EXPIRY_REMINDER_WINDOWS_DAYS = (90, 60, 30, 7, 0)


async def run_once() -> None:
    session_factory = get_session_factory()
    async with session_factory() as session:
        try:
            await _process_overdue_information_requests(session)
            await _process_expiring_documents(session)
            await session.commit()
        except DBAPIError as exc:
            if getattr(exc.orig, "sqlstate", None) == _UNDEFINED_TABLE_SQLSTATE:
                await session.rollback()
                return  # Schema not migrated yet — same tolerance as the outbox dispatcher.
            raise


async def _process_overdue_information_requests(session) -> None:
    requests = SqlAlchemyInformationRequestRepository(session)
    outbox = SqlAlchemyOutboxRepository(session)
    overdue = await requests.list_open_overdue(datetime.date.today())
    for request in overdue:
        request.status = "OVERDUE"
        await outbox.enqueue(
            OnboardingEvent.INFORMATION_REQUESTED,
            {
                "applicationId": str(request.application_id),
                "requestId": str(request.id),
                "notificationCommand": OnboardingNotification.INFORMATION_REQUEST_OVERDUE,
                "channel": "EMAIL",
            },
            aggregate_id=request.application_id,
        )


async def _process_expiring_documents(session) -> None:
    outbox = SqlAlchemyOutboxRepository(session)
    today = datetime.date.today()

    for window_days in _EXPIRY_REMINDER_WINDOWS_DAYS:
        target_date = today + datetime.timedelta(days=window_days)
        stmt = select(OnboardingApplicationDocument).where(
            OnboardingApplicationDocument.current_version.is_(True),
            OnboardingApplicationDocument.expiry_date == target_date,
        )
        documents = (await session.execute(stmt)).scalars().all()
        for document in documents:
            event_type = OnboardingEvent.CREDENTIAL_EXPIRED if window_days == 0 else OnboardingEvent.CREDENTIAL_EXPIRING
            command = (
                OnboardingNotification.CREDENTIAL_EXPIRED
                if window_days == 0
                else OnboardingNotification.CREDENTIAL_EXPIRING
            )
            await outbox.enqueue(
                event_type,
                {
                    "applicationId": str(document.application_id),
                    "documentType": document.document_type,
                    "daysUntilExpiry": window_days,
                    "notificationCommand": command,
                    "channel": "EMAIL",
                },
                aggregate_id=document.application_id,
            )


async def run_polling_loop(interval_seconds: float = 3600.0, stop_event: asyncio.Event | None = None) -> None:
    logger.info("Onboarding scheduled-task loop started (interval=%.0fs)", interval_seconds)
    while stop_event is None or not stop_event.is_set():
        try:
            await run_once()
        except Exception:  # noqa: BLE001 - never let the loop die
            logger.exception("Onboarding scheduled task run failed")
        try:
            if stop_event is not None:
                await asyncio.wait_for(stop_event.wait(), timeout=interval_seconds)
            else:
                await asyncio.sleep(interval_seconds)
        except TimeoutError:
            pass
