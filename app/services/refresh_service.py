"""
Admin refresh orchestration. Runs export + JSON ingestion in the background,
updating the JobStore as the job progresses.

Domain -> function mapping (MongoDB backend):
  menu      -> Excel -> data/json -> MongoDB
  inventory -> Excel -> data/json -> MongoDB
  docs      -> DOCX/menu narratives -> data/json -> MongoDB
  all       -> all three sequentially in one job

With ``DB_BACKEND=postgres`` the same Excel/DOCX -> JSON export runs, then the
JSON is upserted into PostgreSQL (Neon) instead.
"""
from __future__ import annotations

from typing import Any

from app.config import get_settings
from app.ingestion.docs_pipeline import ingest_all_docs
from app.ingestion.excel_inventory import ingest_inventory
from app.ingestion.excel_menu import ingest_menu_catalog
from app.services.jobs import JobStatus, get_job_store, spawn_background

VALID_DOMAINS = ("menu", "inventory", "docs", "all")


async def _run_postgres(domain: str) -> dict[str, Any]:
    from app.backends.postgres.database import ensure_schema, session_scope
    from app.backends.postgres.ingest import ingest_domain_with_export

    await ensure_schema()
    async with session_scope() as session:
        return await ingest_domain_with_export(session, domain)


async def _run_one(domain: str) -> dict:
    if domain not in VALID_DOMAINS:
        raise ValueError(f"unknown domain: {domain}")

    if get_settings().db_backend == "postgres":
        return await _run_postgres(domain)

    if domain == "menu":
        return await ingest_menu_catalog()
    if domain == "inventory":
        return await ingest_inventory()
    if domain == "docs":
        return await ingest_all_docs()
    return {
        "menu": await ingest_menu_catalog(),
        "inventory": await ingest_inventory(),
        "docs": await ingest_all_docs(),
    }


async def _run_job(job_id: str, domain: str) -> None:
    store = get_job_store()
    await store.update(job_id, status=JobStatus.RUNNING, started=True)
    try:
        result = await _run_one(domain)
        await store.update(
            job_id, status=JobStatus.SUCCESS, result=result, finished=True,
        )
    except Exception as exc:  # noqa: BLE001
        await store.update(
            job_id, status=JobStatus.ERROR,
            error=f"{type(exc).__name__}: {exc}", finished=True,
        )


async def enqueue_refresh(domain: str) -> str:
    """Create a Job in PENDING state, spawn the background task, return job_id."""
    store = get_job_store()
    job = await store.create(domain)
    spawn_background(_run_job(job.job_id, domain))
    return job.job_id
