"""
Admin refresh orchestration. Runs ingestion functions in the background,
updates the JobStore as the job progresses.

Domain -> function mapping:
  menu      -> ingest_menu_catalog
  inventory -> ingest_inventory
  docs      -> ingest_all_docs
  all       -> all three sequentially in one job
"""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session_factory
from app.ingestion.docs_pipeline import ingest_all_docs
from app.ingestion.excel_inventory import ingest_inventory
from app.ingestion.excel_menu import ingest_menu_catalog
from app.services.jobs import JobStatus, get_job_store, spawn_background

VALID_DOMAINS = ("menu", "inventory", "docs", "all")


async def _run_one(session: AsyncSession, domain: str) -> dict:
    if domain == "menu":
        return await ingest_menu_catalog(session)
    if domain == "inventory":
        return await ingest_inventory(session)
    if domain == "docs":
        return await ingest_all_docs(session)
    if domain == "all":
        return {
            "menu": await ingest_menu_catalog(session),
            "inventory": await ingest_inventory(session),
            "docs": await ingest_all_docs(session),
        }
    raise ValueError(f"unknown domain: {domain}")


async def _run_job(job_id: str, domain: str) -> None:
    store = get_job_store()
    await store.update(job_id, status=JobStatus.RUNNING, started=True)
    try:
        async with async_session_factory() as session:
            result = await _run_one(session, domain)
            await session.commit()
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
