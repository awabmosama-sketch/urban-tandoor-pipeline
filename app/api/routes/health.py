"""
Health check endpoints. Two names for the same handler:
  GET /health         -> top-level (for monitoring/load balancer)
  GET /api/v1/health  -> under versioned API (for client apps)
Both return the same body.
"""
from __future__ import annotations

from fastapi import APIRouter

import app as app_pkg
from app.runtime import ping_db

router = APIRouter(tags=["health"])


def _version() -> str:
    return getattr(app_pkg, "__version__", "0.1.0")


async def _health_body() -> dict:
    ok, error = await ping_db()
    body: dict = {
        "status": "ok" if ok else "degraded",
        "db": "ok" if ok else "down",
        "version": _version(),
    }
    if error:
        body["db_error"] = error
    return body


@router.get("/health")
async def health_top() -> dict:
    return await _health_body()
