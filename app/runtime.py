"""Backend dispatch for startup, health checks and shutdown.

The active backend is selected with ``DB_BACKEND`` (``mongodb`` or
``postgres``). Importing this module is cheap: the concrete backend modules are
imported lazily only when their functions are called.
"""
from __future__ import annotations

from app.config import get_settings


def backend_name() -> str:
    """Return the active backend (``mongodb`` or ``postgres``)."""
    return get_settings().db_backend


async def ping_db() -> tuple[bool, str | None]:
    """Probe the active database. Never raises."""
    if backend_name() == "postgres":
        from app.backends.postgres.database import ping_db as pg_ping_db

        return await pg_ping_db()

    from app.database import ping_db as mongo_ping_db

    return await mongo_ping_db()


async def ensure_indexes() -> None:
    """Create indexes (MongoDB) or tables (PostgreSQL). Idempotent."""
    if backend_name() == "postgres":
        from app.backends.postgres.database import ensure_schema

        await ensure_schema()
        return

    from app.database import ensure_indexes as mongo_ensure_indexes

    await mongo_ensure_indexes()


async def close_db() -> None:
    """Dispose the active backend's connection pool. Safe to call twice."""
    if backend_name() == "postgres":
        from app.backends.postgres.database import close_db as pg_close_db

        await pg_close_db()
        return

    from app.database import close_db as mongo_close_db

    await mongo_close_db()


__all__ = ["backend_name", "close_db", "ensure_indexes", "ping_db"]
