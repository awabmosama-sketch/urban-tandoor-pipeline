from __future__ import annotations
from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel

from app.config import get_settings
from app.services.jobs import get_job_store
from app.services.refresh_service import VALID_DOMAINS, enqueue_refresh

router = APIRouter(prefix="/admin", tags=["admin"])


def require_admin(x_admin_token: str = Header(..., alias="X-Admin-Token")) -> None:
    expected = get_settings().admin_token
    if not x_admin_token or x_admin_token != expected:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing X-Admin-Token",
        )


class RefreshResponse(BaseModel):
    job_id: str
    domain: str
    status: str


class JobOut(BaseModel):
    job_id: str
    domain: str
    status: str
    created_at: str
    started_at: str | None = None
    finished_at: str | None = None
    result: dict | None = None
    error: str | None = None


@router.post(
    "/refresh/{domain}",
    response_model=RefreshResponse,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_admin)],
)
async def post_refresh(domain: str) -> RefreshResponse:
    if domain not in VALID_DOMAINS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown domain {domain!r}. Valid: {list(VALID_DOMAINS)}",
        )
    job_id = await enqueue_refresh(domain)
    return RefreshResponse(job_id=job_id, domain=domain, status="pending")


@router.get(
    "/jobs/{job_id}",
    response_model=JobOut,
    dependencies=[Depends(require_admin)],
)
async def get_job(job_id: str) -> JobOut:
    store = get_job_store()
    job = await store.get(job_id)
    if job is None:
        raise HTTPException(404, "Job not found")
    return JobOut(**job.to_dict())


@router.get(
    "/jobs",
    response_model=list[JobOut],
    dependencies=[Depends(require_admin)],
)
async def list_jobs(limit: int = 20) -> list[JobOut]:
    if limit < 1 or limit > 100:
        raise HTTPException(400, "limit must be 1..100")
    store = get_job_store()
    jobs = await store.list_recent(limit=limit)
    return [JobOut(**j.to_dict()) for j in jobs]
