"""
In-memory job store for admin refresh operations.

NOT persistent across process restarts — production should use a database
table. For this demo, keeping recent jobs in memory is sufficient and lets
the self-check observe the pending -> running -> success lifecycle.

Thread-safety: guarded by asyncio.Lock. Safe for concurrent calls from the
same event loop (which is all FastAPI runs on).

Task reference handling: asyncio.create_task returns a Task that can be
garbage collected mid-flight if nothing holds a strong reference. We keep
strong refs in _background_tasks until completion.
"""
from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum


class JobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    ERROR = "error"


@dataclass
class Job:
    job_id: str
    domain: str
    status: JobStatus
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    result: dict | None = None
    error: str | None = None

    def to_dict(self) -> dict:
        return {
            "job_id": self.job_id,
            "domain": self.domain,
            "status": self.status.value,
            "created_at": self.created_at.isoformat(),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "result": self.result,
            "error": self.error,
        }


class JobStore:
    def __init__(self, max_history: int = 100) -> None:
        self._jobs: dict[str, Job] = {}
        self._order: list[str] = []          # insertion order for eviction
        self._lock = asyncio.Lock()
        self._max_history = max_history

    async def create(self, domain: str) -> Job:
        async with self._lock:
            job = Job(
                job_id=str(uuid.uuid4()),
                domain=domain,
                status=JobStatus.PENDING,
                created_at=datetime.now(timezone.utc),
            )
            self._jobs[job.job_id] = job
            self._order.append(job.job_id)
            while len(self._order) > self._max_history:
                evict_id = self._order.pop(0)
                self._jobs.pop(evict_id, None)
            return job

    async def get(self, job_id: str) -> Job | None:
        async with self._lock:
            return self._jobs.get(job_id)

    async def list_recent(self, limit: int = 50) -> list[Job]:
        async with self._lock:
            ids = self._order[-limit:]
            return [self._jobs[i] for i in ids if i in self._jobs]

    async def update(
        self,
        job_id: str,
        *,
        status: JobStatus | None = None,
        result: dict | None = None,
        error: str | None = None,
        started: bool = False,
        finished: bool = False,
    ) -> Job | None:
        async with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return None
            if status is not None:
                job.status = status
            if result is not None:
                job.result = result
            if error is not None:
                job.error = error
            if started:
                job.started_at = datetime.now(timezone.utc)
            if finished:
                job.finished_at = datetime.now(timezone.utc)
            return job


# Module-level singleton
_job_store: JobStore | None = None
_background_tasks: set[asyncio.Task] = set()


def get_job_store() -> JobStore:
    global _job_store
    if _job_store is None:
        from app.config import get_settings
        _job_store = JobStore(max_history=get_settings().admin_job_max_history)
    return _job_store


def reset_job_store() -> None:
    """For tests that need a fresh store."""
    global _job_store
    _job_store = None


def spawn_background(coro) -> asyncio.Task:
    """Wrap create_task to keep a strong reference so the task isn't GC'd."""
    task = asyncio.create_task(coro)
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return task
