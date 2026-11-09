"""Async PostgreSQL / Neon engine, session factory and schema bootstrap."""
from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlmodel import SQLModel

from app.backends.postgres import models as _models  # noqa: F401  (registers tables)
from app.config import get_settings


def _normalise_url(url: str) -> str:
    """Accept plain ``postgresql://`` URLs and force the asyncpg driver."""
    if url.startswith("postgresql+asyncpg://"):
        return url
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+asyncpg://", 1)
    return url


settings = get_settings()

engine = create_async_engine(
    _normalise_url(settings.database_url),
    echo=settings.database_echo,
    pool_pre_ping=True,
    # Small pool is plenty for the demo and friendly to the Neon free tier.
    pool_size=5,
    max_overflow=2,
    pool_recycle=300,
)

async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency: one transactional session per request."""
    async with async_session_factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    """Context manager for CLIs and background jobs."""
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def ensure_schema() -> None:
    """Create the 20 tables if they do not exist yet.

    ``create_all`` is idempotent and only creates missing tables. The schema is
    intentionally FK-free, so domain ingestion order does not matter.
    """
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)


async def ping_db() -> tuple[bool, str | None]:
    """Return (ok, error_message). Never raises."""
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True, None
    except Exception as exc:  # noqa: BLE001
        return False, f"{type(exc).__name__}: {exc}"


async def close_db() -> None:
    """Dispose the connection pool. Safe to call more than once."""
    try:
        await engine.dispose()
    except Exception:  # noqa: BLE001
        pass
