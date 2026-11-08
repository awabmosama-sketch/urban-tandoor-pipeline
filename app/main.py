"""
Urban Tandoor & Grill — FastAPI application.

Bootstrap:
  - Lifespan: MongoDB index bootstrap + ping (non-fatal), shutdown client close
  - Middlewares: RequestID (outermost), CORS, GZip (innermost)
  - Routes: /health (top-level, back-compat), /api/v1/* (versioned)
  - Docs: /docs (Swagger UI), /redoc (ReDoc), /openapi.json
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

import app as app_pkg
from app.api.middleware import RequestIDMiddleware
from app.api.routes import api_router
from app.api.routes.health import router as health_router
from app.database import close_db, ensure_indexes, ping_db

STATIC_DIR = Path(__file__).resolve().parent / "static"


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Startup: probe MongoDB but NEVER block startup on failure.
    ok, error = await ping_db()
    if ok:
        print("[startup] MongoDB reachable", flush=True)
        try:
            await ensure_indexes()
            print("[startup] MongoDB indexes ready", flush=True)
        except Exception as exc:  # noqa: BLE001
            print(f"[startup] index bootstrap skipped: {exc}", flush=True)
    else:
        print(f"[startup] MongoDB unreachable at boot: {error}", flush=True)
    try:
        yield
    finally:
        try:
            await close_db()
            print("[shutdown] MongoDB client closed", flush=True)
        except Exception as exc:  # noqa: BLE001
            print(f"[shutdown] MongoDB close error: {exc}", flush=True)


app = FastAPI(
    title="Urban Tandoor & Grill — Menu & Inventory API",
    description=(
        "Async FastAPI + MongoDB Atlas for menu, inventory, availability and "
        "retrieval. Data is ingested from JSON snapshots. All data is synthetic "
        "demo data."
    ),
    version=getattr(app_pkg, "__version__", "0.1.0"),
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
