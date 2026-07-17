"""Generic transactional-outbox dispatcher.

Every module that owns its own `event_outbox` table (Identity, Onboarding,
and future modules) reuses this rather than re-implementing the same
polling/locking/retry mechanics. Each module supplies its own ORM model
(matching the standard outbox shape: `id`, `status`, `created_at`,
`payload`, `attempts`, `last_error`, `processed_at`) and a `deliver`
callback; this class owns everything else, including graceful handling of
"the table doesn't exist yet because migrations haven't run" (see
`app/modules/identity/application/outbox_dispatcher.py`'s module
docstring for the incident that motivated this).
"""

from __future__ import annotations

import asyncio
import datetime
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

logger = logging.getLogger(__name__)

# PostgreSQL SQLSTATE for "undefined_table" — see
# https://www.postgresql.org/docs/current/errcodes-appendix.html. More
# robust than matching a specific driver exception class since it's
# exposed as `.sqlstate` regardless of how SQLAlchemy's dialect wraps it.
_UNDEFINED_TABLE_SQLSTATE = "42P01"

DeliverFn = Callable[[Any, AsyncSession], Awaitable[None]]


class OutboxDispatcher:
    def __init__(
        self,
        *,
        name: str,
        session_factory: async_sessionmaker,
        model: type,
        deliver: DeliverFn,
        batch_size: int = 25,
        max_attempts: int = 5,
    ) -> None:
        self._name = name
        self._session_factory = session_factory
        self._model = model
        self._deliver = deliver
        self._batch_size = batch_size
        self._max_attempts = max_attempts
        self._warned_schema_not_ready = False

    async def dispatch_once(self) -> int:
        """Processes a single batch. Returns the number of rows processed."""
        model = self._model
        async with self._session_factory() as session:
            stmt = (
                select(model)
                .where(model.status == "PENDING")
                .order_by(model.created_at)
                .limit(self._batch_size)
                .with_for_update(skip_locked=True)
            )
            try:
                rows = list((await session.execute(stmt)).scalars().all())
            except DBAPIError as exc:
                if getattr(exc.orig, "sqlstate", None) == _UNDEFINED_TABLE_SQLSTATE:
                    if not self._warned_schema_not_ready:
                        logger.warning(
                            "[%s] outbox table not found yet — waiting for migrations "
                            "('alembic upgrade head') to run. This message won't repeat.",
                            self._name,
                        )
                        self._warned_schema_not_ready = True
                    await session.rollback()
                    return 0
                raise

            self._warned_schema_not_ready = False
            if not rows:
                return 0

            for row in rows:
                row.status = "PROCESSING"
            await session.flush()

            for row in rows:
                try:
                    await self._deliver(row, session)
                    row.status = "PROCESSED"
                    row.processed_at = datetime.datetime.now(datetime.UTC)
                except Exception as exc:  # noqa: BLE001 - isolate failures per-row
                    row.attempts += 1
                    row.last_error = str(exc)[:2000]
                    row.status = "FAILED" if row.attempts >= self._max_attempts else "PENDING"
                    logger.warning("[%s] dispatch failed for event %s: %s", self._name, row.id, exc)

            await session.commit()
            return len(rows)

    async def run_polling_loop(
        self, interval_seconds: float = 2.0, stop_event: asyncio.Event | None = None
    ) -> None:
        logger.info("[%s] outbox dispatcher started (interval=%.1fs)", self._name, interval_seconds)
        while stop_event is None or not stop_event.is_set():
            try:
                processed = await self.dispatch_once()
                if processed:
                    logger.info("[%s] outbox dispatcher processed %d event(s)", self._name, processed)
            except Exception:  # noqa: BLE001 - never let the poller die
                logger.exception("[%s] outbox dispatcher tick failed", self._name)
            try:
                if stop_event is not None:
                    await asyncio.wait_for(stop_event.wait(), timeout=interval_seconds)
                else:
                    await asyncio.sleep(interval_seconds)
            except TimeoutError:
                pass
