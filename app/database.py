"""Async MongoDB Atlas connection, dependency and index bootstrap."""

from __future__ import annotations

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from app.collections import COMPOUND_UNIQUE_INDEXES, INDEX_SPECS
from app.config import get_settings

_client: AsyncIOMotorClient | None = None
_db_override: AsyncIOMotorDatabase | None = None


def get_client() -> AsyncIOMotorClient:
    """Return the process-wide Motor client (created lazily)."""
    global _client
    if _client is None:
        settings = get_settings()
        _client = AsyncIOMotorClient(
            settings.mongodb_uri,
            serverSelectionTimeoutMS=settings.mongodb_timeout_ms,
            uuidRepresentation="standard",
        )
    return _client


def get_db() -> AsyncIOMotorDatabase:
    """FastAPI dependency: the configured database handle."""
    if _db_override is not None:
        return _db_override
    return get_client()[get_settings().mongodb_db]


def set_db_override(db: AsyncIOMotorDatabase | None) -> None:
    """Test hook: point the whole app at an in-memory database."""
    global _db_override
    _db_override = db


async def ensure_indexes(db: AsyncIOMotorDatabase | None = None) -> None:
    """Create the unique/query indexes needed by upserts and read paths."""
    database = db if db is not None else get_db()
    for name, specs in INDEX_SPECS.items():
        for fields, options in specs:
            keys = [(field, 1) for field in fields]
            await database[name].create_index(keys, **options)
    for name, specs in COMPOUND_UNIQUE_INDEXES.items():
        for fields, options in specs:
            keys = [(field, 1) for field in fields]
            await database[name].create_index(keys, **options)


async def ping_db() -> tuple[bool, str | None]:
    """Return (ok, error_message). Never raises."""
    try:
        await get_db().list_collection_names()
        return True, None
    except Exception as exc:  # noqa: BLE001
        return False, f"{type(exc).__name__}: {exc}"


async def close_db() -> None:
    """Close the Motor client. Safe to call more than once."""
    global _client
    if _client is not None:
        _client.close()
        _client = None
