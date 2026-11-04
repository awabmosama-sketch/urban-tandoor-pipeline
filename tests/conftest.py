"""
Shared pytest fixtures.

Design:
  - FastAPI app is constructed ONCE per session (module-scoped).
  - Each test gets a fresh httpx.AsyncClient (function-scoped).
  - DB queries use the app's async_session_factory directly.
  - Admin headers fixture provides the default X-Admin-Token.

Why httpx.AsyncClient + ASGITransport: exercises real ASGI middleware chain
(RequestID, CORS, GZip) without spinning up a network server. Faster, safer.

pytest-asyncio runs every async test on its own event loop, so pooled
asyncpg connections are disposed after each test to prevent
"attached to a different loop" errors.
"""
from __future__ import annotations

from collections.abc import AsyncIterator

import httpx
import pytest
import pytest_asyncio

from app.config import get_settings
from app.database import async_session_factory, engine
from app.main import app


@pytest.fixture(scope="session")
def settings():
    return get_settings()


@pytest.fixture(scope="session")
def admin_headers(settings) -> dict:
    return {"X-Admin-Token": settings.admin_token}


@pytest_asyncio.fixture(autouse=True)
async def _dispose_engine() -> AsyncIterator[None]:
    """Close pooled connections before each test's event loop shuts down."""
    yield
    await engine.dispose()


@pytest_asyncio.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest_asyncio.fixture
async def db_session():
    async with async_session_factory() as session:
        yield session


# ---- DB helper fixture ----
class DB:
    def __init__(self, session):
        self.session = session

    async def count(self, table: str) -> int:
        from sqlalchemy import text
        r = await self.session.execute(text(f"SELECT COUNT(*) FROM {table}"))
        return r.scalar() or 0

    async def scalar(self, sql: str, **params):
        from sqlalchemy import text
        r = await self.session.execute(text(sql), params)
        return r.scalar()

    async def first(self, sql: str, **params):
        from sqlalchemy import text
        r = await self.session.execute(text(sql), params)
        row = r.first()
        return dict(row._mapping) if row else None

    async def all(self, sql: str, **params):
        from sqlalchemy import text
        r = await self.session.execute(text(sql), params)
        return [dict(x._mapping) for x in r]


@pytest_asyncio.fixture
async def db(db_session) -> DB:
    return DB(db_session)
