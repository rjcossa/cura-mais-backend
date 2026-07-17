"""Async SQLAlchemy engine and session factory."""

from __future__ import annotations

import datetime
from collections.abc import AsyncGenerator

from sqlalchemy import DateTime
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.core.config import get_settings
from app.core.exceptions import AppError


class Base(DeclarativeBase):
    """Shared declarative base for all ORM models in the application.

    Each module owns its own tables (see module docstrings), but they share
    a single Base/metadata so that Alembic can autogenerate against the full
    schema as more modules are added.
    """

    # Every `Mapped[datetime.datetime]` column maps to TIMESTAMPTZ by
    # default, matching the spec's DDL (`TIMESTAMPTZ NOT NULL DEFAULT
    # CURRENT_TIMESTAMP`) without having to repeat `DateTime(timezone=True)`
    # on every single column definition.
    type_annotation_map = {datetime.datetime: DateTime(timezone=True)}


_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        settings = get_settings()
        _engine = create_async_engine(
            settings.database_url,
            echo=settings.database_echo,
            pool_size=settings.database_pool_size,
            max_overflow=settings.database_max_overflow,
            pool_pre_ping=True,
        )
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(
            bind=get_engine(),
            expire_on_commit=False,
            autoflush=False,
        )
    return _session_factory


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency yielding a request-scoped database session.

    Commits on clean exit. Also commits (rather than rolls back) when an
    `AppError` is raised: services frequently stage legitimate side effects
    alongside an "expected" business rejection — e.g. incrementing
    `failed_login_attempts` and locking the account while still raising
    `INVALID_CREDENTIALS`, or writing a security event before raising
    `REFRESH_TOKEN_REUSE_DETECTED`. Those writes must survive even though
    the primary operation is being rejected. Only genuinely unexpected
    exceptions (bugs, DB errors, etc.) trigger a rollback.
    """
    session_factory = get_session_factory()
    async with session_factory() as session:
        try:
            yield session
        except AppError:
            await session.commit()
            raise
        except Exception:
            await session.rollback()
            raise
        else:
            await session.commit()


async def dispose_engine() -> None:
    global _engine
    if _engine is not None:
        await _engine.dispose()
        _engine = None
