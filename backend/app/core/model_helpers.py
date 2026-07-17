"""Small shared helpers for ORM model definitions, so each module's
`domain/models.py` doesn't repeat the same boilerplate.
"""

from __future__ import annotations

import uuid

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column


def uuid_pk() -> Mapped[uuid.UUID]:
    """A UUID primary key with a server-side `gen_random_uuid()` default —
    every table across both the Identity and Onboarding specs uses
    `id UUID PRIMARY KEY DEFAULT gen_random_uuid()`.
    """
    return mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
