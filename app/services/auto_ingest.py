"""Automatic JSON snapshot ingestion for the API process.

The repository's ``data/json/*.json`` files are the canonical source of truth.
This module makes the API keep the selected database in sync with them:

* once at startup (only domains whose fingerprint changed, or everything when
  the database is empty), and
* in the background while the process is running, so editing a JSON file never
  leaves a stale menu behind.

Per-domain SHA-256 fingerprints are stored in ``_pipeline_meta`` (MongoDB) or
``pipeline_meta`` (PostgreSQL). Upserts are already idempotent, so a re-ingest
is safe. Failures are logged and never prevent the API from starting.
"""
from __future__ import annotations

import asyncio
import hashlib
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.collections import DOCS_COLLECTIONS, INVENTORY_COLLECTIONS, MENU_COLLECTIONS
from app.config import get_settings

DOMAIN_COLLECTIONS: dict[str, tuple[str, ...]] = {
    "menu": MENU_COLLECTIONS,
    "inventory": INVENTORY_COLLECTIONS,
    "docs": DOCS_COLLECTIONS,
}
DOMAINS = tuple(DOMAIN_COLLECTIONS)

_META_KEY = "json_fingerprints"
_MONGO_META_COLLECTION = "_pipeline_meta"

_lock = asyncio.Lock()
_task: asyncio.Task | None = None
_stop: asyncio.Event | None = None


def compute_fingerprints(directory: str | Path | None = None) -> dict[str, str]:
    """Hash the JSON files belonging to each domain.

    A missing file still produces a stable hash, so adding it later is detected
    as a change and triggers ingestion.
    """
    json_dir = Path(directory or get_settings().json_dir)
    fingerprints: dict[str, str] = {}
    for domain, names in DOMAIN_COLLECTIONS.items():
        digest = hashlib.sha256()
        for name in names:
            path = json_dir / f"{name}.json"
            digest.update(name.encode("utf-8"))
            digest.update(path.read_bytes() if path.is_file() else b"<missing>")
        fingerprints[domain] = digest.hexdigest()
    return fingerprints


async def _read_fingerprints() -> dict[str, str]:
    if get_settings().db_backend == "postgres":
        from app.backends.postgres.database import session_scope
        from app.backends.postgres.models import PipelineMeta

        async with session_scope() as session:
            row = await session.get(PipelineMeta, _META_KEY)
            return dict(row.fingerprints) if row else {}

    from app.database import get_db

    doc = await get_db()[_MONGO_META_COLLECTION].find_one({"_id": _META_KEY})
    return dict(doc.get("fingerprints", {})) if doc else {}


async def _write_fingerprints(fingerprints: dict[str, str]) -> None:
    now = datetime.now(UTC)
    if get_settings().db_backend == "postgres":
        from sqlalchemy.dialects.postgresql import insert as pg_insert

        from app.backends.postgres.database import session_scope
        from app.backends.postgres.models import PipelineMeta

        async with session_scope() as session:
            statement = pg_insert(PipelineMeta).values(
                key=_META_KEY, fingerprints=fingerprints, updated_at=now
            )
            statement = statement.on_conflict_do_update(
                index_elements=["key"],
                set_={
                    "fingerprints": statement.excluded.fingerprints,
                    "updated_at": statement.excluded.updated_at,
                },
            )
            await session.execute(statement)
        return

    from app.database import get_db

    await get_db()[_MONGO_META_COLLECTION].update_one(
        {"_id": _META_KEY},
        {"$set": {"fingerprints": fingerprints, "updated_at": now}},
        upsert=True,
    )


async def _database_is_empty() -> bool:
    """Detect a fresh/wiped database even if the stored fingerprint matches."""
    if get_settings().db_backend == "postgres":
        from sqlalchemy import func, select

        from app.backends.postgres.database import session_scope
        from app.backends.postgres.models import MenuItem

        async with session_scope() as session:
            count = (
                await session.execute(select(func.count()).select_from(MenuItem))
            ).scalar_one()
        return int(count) == 0

    from app.database import get_db

    return await get_db().menu_items.count_documents({}) == 0


async def _ingest_domain(domain: str) -> dict[str, int]:
    if get_settings().db_backend == "postgres":
        from app.backends.postgres.database import session_scope
        from app.backends.postgres.ingest import ingest_json_domain as pg_ingest

        async with session_scope() as session:
            return await pg_ingest(session, domain)

    from app.database import get_db
    from app.ingestion.json_ingest import ingest_json_domain

    return await ingest_json_domain(get_db(), domain)


async def sync_once(*, force: bool = False) -> dict[str, Any]:
    """Ingest every domain whose JSON changed. Returns a JSON-friendly report."""
    current = compute_fingerprints()
    stored = await _read_fingerprints()
    empty = await _database_is_empty()

    changed = [
        domain
        for domain in DOMAINS
        if force or empty or current[domain] != stored.get(domain)
    ]
    report: dict[str, Any] = {
        "changed": changed,
        "ingested": [],
        "failed": [],
        "empty_database": empty,
    }

    for domain in changed:
        try:
            counts = await _ingest_domain(domain)
        except Exception as exc:  # noqa: BLE001 - a bad snapshot must not kill boot
            message = f"{type(exc).__name__}: {exc}"
            report["failed"].append({"domain": domain, "error": message})
            print(f"[auto-ingest] {domain}: ERROR {message}", file=sys.stderr, flush=True)
            continue

        report["ingested"].append({"domain": domain, "counts": counts})
        # Persist each successful domain so a later failure is retried alone.
        stored[domain] = current[domain]
        await _write_fingerprints(stored)
        print(f"[auto-ingest] {domain}: loaded from JSON", file=sys.stderr, flush=True)

    return report


async def run_at_startup() -> dict[str, Any] | None:
    """Called from the FastAPI lifespan. Always non-fatal."""
    settings = get_settings()
    if not settings.auto_ingest_on_startup:
        return None
    try:
        report = await sync_once()
    except Exception as exc:  # noqa: BLE001
        message = f"{type(exc).__name__}: {exc}"
        print(f"[auto-ingest] startup check failed: {message}", file=sys.stderr, flush=True)
        return {"error": message}

    loaded = [entry["domain"] for entry in report["ingested"]]
    print(
        f"[auto-ingest] startup: domains={list(DOMAINS)} loaded={loaded}",
        file=sys.stderr,
        flush=True,
    )
    return report


async def _watch_loop(poll_seconds: float, stop_event: asyncio.Event) -> None:
    previous = compute_fingerprints()
    candidate: dict[str, str] | None = None

    while not stop_event.is_set():
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=poll_seconds)
            return  # stop requested
        except TimeoutError:
            pass

        current = compute_fingerprints()
        if current == previous:
            candidate = None
            continue
        if candidate != current:
            # Debounce: require two identical readings so a half-written JSON
            # file is never ingested.
            candidate = current
            continue
        candidate = None

        async with _lock:
            try:
                await sync_once()
            except Exception as exc:  # noqa: BLE001
                print(
                    f"[auto-ingest] watch failed: {type(exc).__name__}: {exc}",
                    file=sys.stderr,
                    flush=True,
                )
        # Re-read from storage: a failed ingest remains "changed" and is retried.
        try:
            previous = await _read_fingerprints()
        except Exception as exc:  # noqa: BLE001
            previous = current
            print(
                f"[auto-ingest] could not read fingerprints: {exc}",
                file=sys.stderr,
                flush=True,
            )


def start_watcher() -> asyncio.Task | None:
    """Start the background JSON watcher. Safe to call more than once."""
    global _task, _stop
    settings = get_settings()
    if not settings.auto_ingest_watch or (_task is not None and not _task.done()):
        return _task
    _stop = asyncio.Event()
    _task = asyncio.create_task(_watch_loop(settings.auto_ingest_poll_seconds, _stop))
    return _task


async def stop_watcher() -> None:
    """Cancel the watcher before the database connection pool is closed."""
    global _task, _stop
    if _stop is not None:
        _stop.set()
    if _task is not None:
        _task.cancel()
        try:
            await _task
        except asyncio.CancelledError:
            pass
        _task = None
    _stop = None


__all__ = [
    "DOMAINS",
    "compute_fingerprints",
    "run_at_startup",
    "start_watcher",
    "stop_watcher",
    "sync_once",
]
