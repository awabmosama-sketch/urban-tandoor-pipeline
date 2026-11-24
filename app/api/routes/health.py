"""
Health check endpoints. Two names for the same handler:
  GET /health         -> top-level (for monitoring/load balancer)
  GET /api/v1/health  -> under versioned API (for client apps)
Both return the same body.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter

from app.runtime import ping_db
from app.version import app_version

logger = logging.getLogger(__name__)

router = APIRouter(tags=["health"])


def _version() -> str:
    return app_version()


async def _health_body() -> dict:
    ok, error = await ping_db()
    if error:
        # Full diagnostics belong in server logs, not in a public endpoint:
        # DB errors can contain hosts, users or DSN fragments.
        logger.warning("Database health check failed: %s", error)
    return {
        "status": "ok" if ok else "degraded",
        "db": "ok" if ok else "down",
        "version": _version(),
    }


@router.get("/health")
async def health_top() -> dict:
    return await _health_body()
