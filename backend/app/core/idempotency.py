"""Idempotency-Key support for write endpoints (spec section 24).

Usage in a route handler::

    stored = await get_idempotent_response(db, "auth.register.patient", key, body_bytes)
    if stored is not None:
        return JSONResponse(status_code=stored.status, content=stored.body)
    ... do the real work, build `response_body` ...
    await save_idempotent_response(db, "auth.register.patient", key, body_bytes, 201, response_body)
"""

from __future__ import annotations

import datetime
import hashlib
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import IdempotencyKeyReusedError
from app.core.models import IdempotencyKey

_DEFAULT_TTL = datetime.timedelta(hours=24)


@dataclass(slots=True)
class StoredResponse:
    status: int
    body: dict


def hash_request_body(raw_body: bytes) -> str:
    return hashlib.sha256(raw_body).hexdigest()


async def get_idempotent_response(
    db: AsyncSession, endpoint: str, idempotency_key: str, raw_body: bytes
) -> StoredResponse | None:
    request_hash = hash_request_body(raw_body)
    stmt = select(IdempotencyKey).where(
        IdempotencyKey.endpoint == endpoint, IdempotencyKey.idempotency_key == idempotency_key
    )
    existing = (await db.execute(stmt)).scalar_one_or_none()
    if existing is None:
        return None
    if existing.request_hash != request_hash:
        raise IdempotencyKeyReusedError()
    return StoredResponse(status=existing.response_status, body=existing.response_body)


async def save_idempotent_response(
    db: AsyncSession,
    endpoint: str,
    idempotency_key: str,
    raw_body: bytes,
    status: int,
    body: dict,
) -> None:
    record = IdempotencyKey(
        endpoint=endpoint,
        idempotency_key=idempotency_key,
        request_hash=hash_request_body(raw_body),
        response_status=status,
        response_body=body,
        expires_at=datetime.datetime.now(datetime.UTC) + _DEFAULT_TTL,
    )
    db.add(record)
    await db.flush()
