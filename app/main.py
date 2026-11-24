"""
Urban Tandoor & Grill — FastAPI application.

Bootstrap:
  - Lifespan: index/schema bootstrap + ping (non-fatal), shutdown pool close
  - Backend is selected with DB_BACKEND=mongodb|postgres (see app/runtime.py)
  - Middlewares: RequestID (outermost), CORS, GZip (innermost)
  - Routes: /health (top-level, back-compat), /api/v1/* (versioned)
  - Docs: /docs (Swagger UI), /redoc (ReDoc), /openapi.json
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.api.middleware import RequestIDMiddleware
from app.api.routes import api_router
from app.api.routes.health import router as health_router
from app.runtime import backend_name, close_db, ensure_indexes, ping_db
from app.services.auto_ingest import run_at_startup, start_watcher, stop_watcher
from app.services.jobs import cancel_background_tasks
from app.version import app_version

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).resolve().parent / "static"


@asynccontextmanager
async def lifespan(_app: FastAPI):
    backend = backend_name()
    watcher = None
    # Probe the database but NEVER block startup on failure.
    ok, error = await ping_db()
    if ok:
        logger.info("[startup] %s reachable", backend)
        try:
            await ensure_indexes()
            logger.info("[startup] %s indexes/schema ready", backend)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[startup] index/schema bootstrap skipped: %s", exc)
    else:
        logger.warning("[startup] %s unreachable at boot: %s", backend, error)

    # JSON is the source of truth. Both steps tolerate DB outages; the watcher
    # must start even when the boot probe failed so the app can self-heal.
    try:
        await run_at_startup()
    except Exception as exc:  # noqa: BLE001
        logger.warning("[startup] auto-ingest skipped: %s", exc)
    watcher = start_watcher()

    try:
        yield
    finally:
        # Nested try/finally guarantees the pool is closed even if one step fails.
        try:
            if watcher is not None:
                await stop_watcher()
        finally:
            try:
                await cancel_background_tasks()
            finally:
                try:
                    await close_db()
                    logger.info("[shutdown] %s connection closed", backend)
                except Exception:  # noqa: BLE001
                    logger.exception("[shutdown] %s close error", backend)


app = FastAPI(
    title="Urban Tandoor & Grill — Menu & Inventory API",
    description=(
        "Async FastAPI + MongoDB Atlas / PostgreSQL (Neon) for menu, inventory, "
        "availability and retrieval. Data is ingested from JSON snapshots. All "
        "data is synthetic demo data."
    ),
    version=app_version(),
    lifespan=lifespan,
)

# --- Middleware order: last-added is OUTERMOST (runs first on request) ---
# Desired: RequestID (outermost) -> CORS -> GZip (innermost)
app.add_middleware(GZipMiddleware, minimum_size=1024)          # innermost
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Request-ID"],
)
app.add_middleware(RequestIDMiddleware)                        # outermost

# --- Routes ---
# Top-level /health for back-compat with Phase 1 tests.
app.include_router(health_router)
# Versioned API.
app.include_router(api_router)


# --- Frontend ---
@app.get("/", include_in_schema=False)
async def root() -> RedirectResponse:
    """Send the root to the hand-built frontend."""
    return RedirectResponse(url="/ui/")


app.mount("/ui", StaticFiles(directory=STATIC_DIR, html=True), name="ui")
