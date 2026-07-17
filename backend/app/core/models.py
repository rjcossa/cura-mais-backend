"""ORM models for cross-cutting platform concerns that don't belong to any
single business module. Currently just idempotency-key storage (spec
section 24) — any module's endpoints may use this, not just Identity's.
"""

from __future__ import annotations

import datetime
import uuid

from sqlalchemy import Index, Integer, String, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class IdempotencyKey(Base):
    __tablename__ = "idempotency_keys"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )

    # `endpoint` scopes the client-supplied key so the same key value can't
    # collide across unrelated endpoints.
    endpoint: Mapped[str] = mapped_column(String(150), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    response_status: Mapped[int] = mapped_column(Integer, nullable=False)
    response_body: Mapped[dict] = mapped_column(JSONB, nullable=False)

    created_at: Mapped[datetime.datetime] = mapped_column(server_default=func.now())
    expires_at: Mapped[datetime.datetime] = mapped_column(nullable=False)

    __table_args__ = (
        Index("ux_idempotency_endpoint_key", "endpoint", "idempotency_key", unique=True),
    )
