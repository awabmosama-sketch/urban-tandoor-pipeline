"""Process-wide serialization for JSON export/ingest operations.

Admin refreshes and the auto-ingest watcher both write the canonical JSON
snapshots and upsert them into the active database. Serializing those writers
prevents torn files and interleaved old/new upserts from being observed by API
readers. The lock is process-local, which matches the in-memory job store.
"""
from __future__ import annotations

import asyncio

_lock = asyncio.Lock()


def get_ingest_lock() -> asyncio.Lock:
    """Return the shared export/ingest lock for this process."""
    return _lock


__all__ = ["get_ingest_lock"]
