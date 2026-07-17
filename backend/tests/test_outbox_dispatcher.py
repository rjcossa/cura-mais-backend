"""Tests for the transactional outbox dispatcher, including its resilience
to the app starting before migrations have run (the exact scenario that
caused log-spamming stack traces in earlier versions of this module)."""

from __future__ import annotations

from sqlalchemy import select, text

from app.core.database import get_engine
from app.modules.identity.application.outbox_dispatcher import dispatch_once
from app.modules.identity.domain.models import EventOutbox
from tests.conftest import patient_payload


async def test_dispatch_once_delivers_pending_email_event(client, session_factory):
    await client.post("/api/v1/auth/register/patient", json=patient_payload())

    processed = await dispatch_once()
    assert processed > 0

    async with session_factory() as session:
        rows = (await session.execute(select(EventOutbox))).scalars().all()
        assert all(r.status in {"PROCESSED", "PENDING"} for r in rows)
        # The email-verification event specifically must have been delivered.
        email_events = [r for r in rows if r.event_type == "EmailVerificationRequested"]
        assert email_events and email_events[0].status == "PROCESSED"


async def test_dispatch_once_is_idempotent_when_nothing_pending(client):
    await client.post("/api/v1/auth/register/patient", json=patient_payload())
    await dispatch_once()  # drains the queue

    processed_again = await dispatch_once()
    assert processed_again == 0


async def test_dispatcher_survives_missing_table_without_raising(session_factory):
    """Reproduces the scenario reported after the Postgres 18 volume fix:
    the app (and its background outbox dispatcher) starting before
    `alembic upgrade head` has created the schema. This must degrade
    gracefully — return 0, not raise — rather than spam a traceback on
    every 2-second tick.
    """
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.execute(text("DROP TABLE IF EXISTS event_outbox"))

    try:
        result = await dispatch_once()
        assert result == 0  # must not raise

        # A second call while still missing should also stay quiet and safe.
        result2 = await dispatch_once()
        assert result2 == 0
    finally:
        # Recreate so later tests (and the autouse truncate fixture) see a
        # consistent schema again.
        async with engine.begin() as conn:
            await conn.run_sync(lambda sync_conn: EventOutbox.__table__.create(sync_conn, checkfirst=True))


async def test_dispatcher_resumes_normally_after_table_appears(client, session_factory):
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.execute(text("DROP TABLE IF EXISTS event_outbox"))

    await dispatch_once()  # table missing: must not raise

    async with engine.begin() as conn:
        await conn.run_sync(lambda sync_conn: EventOutbox.__table__.create(sync_conn, checkfirst=True))

    await client.post("/api/v1/auth/register/patient", json=patient_payload())
    processed = await dispatch_once()
    assert processed > 0  # back to normal once the schema exists
