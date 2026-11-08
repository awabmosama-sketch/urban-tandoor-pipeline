"""
Shared pytest fixtures.

Design:
  - Every test runs against an in-memory MongoDB (``mongomock-motor``), so the
    suite needs no Atlas connection and no network access.
  - The database is seeded once per session through the same JSON ingestion
    path production uses: ``data/json/<collection>.json`` -> collections.
  - All writes are idempotent upserts and the refresh tests re-ingest the same
    JSON, so a shared seeded database stays deterministic.
  - The FastAPI app is exercised over ASGI with ``httpx.AsyncClient`` so the
    real middleware chain and routes are covered without a network server.
"""
from __future__ import annotations

import os

# Force deterministic, offline embeddings regardless of the developer's .env.
os.environ["EMBEDDING_PROVIDER"] = "fake"
os.environ["EMBEDDING_DIM"] = "1536"

from collections.abc import AsyncIterator  # noqa: E402

import httpx  # noqa: E402
import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from mongomock_motor import AsyncMongoMockClient  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.database import ensure_indexes, set_db_override  # noqa: E402
from app.ingestion.json_ingest import ingest_all_json  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture(scope="session")
def settings():
    get_settings.cache_clear()
    return get_settings()


@pytest.fixture(scope="session")
def admin_headers(settings) -> dict:
    return {"X-Admin-Token": settings.admin_token}


@pytest_asyncio.fixture(scope="session", loop_scope="session", autouse=True)
async def seeded_db() -> AsyncIterator:
    """One in-memory MongoDB for the whole session, seeded from JSON snapshots.

    Every write path in the app is an idempotent upsert on a natural key, and
    the refresh tests re-ingest the same canonical JSON, so sharing one seeded
    database does not make tests order-dependent.
    """
    client = AsyncMongoMockClient()
    database = client[f"{get_settings().mongodb_db}_test"]
    set_db_override(database)
    await ensure_indexes(database)
    await ingest_all_json(database)
    try:
        yield database
    finally:
        set_db_override(None)
        client.close()


@pytest_asyncio.fixture
async def db(seeded_db):
    """Raw async MongoDB database handle for assertions."""
    return seeded_db


@pytest_asyncio.fixture
async def client(seeded_db) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
