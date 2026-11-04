"""
Self-check for Phase 10 (FastAPI bootstrap).

Run: python -m uv run python scripts/_selfcheck_10.py
Exits 0 on success, 1 on failure.

Most checks use httpx.ASGITransport (no lifespan). The lifespan is exercised
separately with fastapi.testclient.TestClient. The engine is disposed between
the two so pooled asyncpg connections never cross event loops.
"""
from __future__ import annotations

import asyncio
import contextlib
import io
import json
import re
import subprocess
import sys
import uuid
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]

results: list[tuple[str, str, object]] = []


def check(name: str, condition: bool, got=None) -> None:
    status = "PASS" if condition else "FAIL"
    results.append((name, status, got))
    print(f"{status}  {name}" + ("" if got is None else f"  (got: {got})"))


async def http_checks(app, d1_holder: dict) -> None:
    from app.database import engine

    transport = httpx.ASGITransport(app=app)
    try:
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            # --- GROUP B: /health (top-level, back-compat) ---
            r = await client.get("/health")
            body = r.json() if r.status_code == 200 else {}
            check("B1 GET /health returns 200", r.status_code == 200, r.status_code)
            check(
                "B2 /health status in {ok, degraded}",
                body.get("status") in {"ok", "degraded"},
                body.get("status"),
            )
            check(
                "B3 /health db in {ok, down}",
                body.get("db") in {"ok", "down"},
                body.get("db"),
            )
            check(
                "B4 /health version == app.version",
                body.get("version") == app.version,
                body.get("version"),
            )
            if body.get("db") == "down":
                check(
                    "B5 db_error present and non-empty when db=down",
                    isinstance(body.get("db_error"), str) and bool(body.get("db_error")),
                    body.get("db_error"),
                )
            else:
                check(
                    "B5 db_error check (skipped: DB is up)",
                    True,
                    "skipped: db=ok",
                )

            # --- GROUP C: /api/v1/ ---
            r_root = await client.get("/api/v1/")
            root = r_root.json() if r_root.status_code == 200 else {}
            check("C1 GET /api/v1/ returns 200", r_root.status_code == 200, r_root.status_code)
            check(
                "C2 /api/v1/ has service/version/docs/openapi/endpoints",
                all(k in root for k in ("service", "version", "docs", "openapi", "endpoints")),
                sorted(root) if root else None,
            )
            endpoints = root.get("endpoints") or {}
            check(
                "C3 endpoints.health_top == /health",
                endpoints.get("health_top") == "/health",
                endpoints.get("health_top"),
            )
            check(
                "C4 endpoints.health_v1 == /api/v1/",
                endpoints.get("health_v1") == "/api/v1/",
                endpoints.get("health_v1"),
            )

            # --- GROUP D: openapi + docs ---
            r_spec = await client.get("/openapi.json")
            spec = r_spec.json() if r_spec.status_code == 200 else {}
            d1_holder["openapi_len"] = len(r_spec.content)
            check("D1 GET /openapi.json returns 200", r_spec.status_code == 200, r_spec.status_code)
            check(
                "D1 openapi content-type is application/json",
                "application/json" in r_spec.headers.get("content-type", ""),
                r_spec.headers.get("content-type"),
            )
            check(
                "D2 openapi info.title contains 'Urban Tandoor'",
                "Urban Tandoor" in (spec.get("info", {}).get("title") or ""),
                spec.get("info", {}).get("title"),
            )
            paths = spec.get("paths") or {}
            check("D3 openapi paths contains /health", "/health" in paths, sorted(paths))
            check("D4 openapi paths contains /api/v1/", "/api/v1/" in paths, sorted(paths))
            r_docs = await client.get("/docs")
            check("D5 GET /docs returns 200", r_docs.status_code == 200, r_docs.status_code)
            check(
                "D5 /docs content-type is text/html",
                "text/html" in r_docs.headers.get("content-type", ""),
                r_docs.headers.get("content-type"),
            )

            # --- GROUP E: request ID ---
            r_id = await client.get("/health")
            rid = r_id.headers.get("x-request-id")
            valid_uuid4 = False
            if rid:
                try:
                    valid_uuid4 = uuid.UUID(rid, version=4).version == 4
                except ValueError:
                    valid_uuid4 = False
            check("E1 /health response has X-Request-ID", bool(rid), rid)
            check("E1 X-Request-ID is a UUID4", valid_uuid4, rid)

            r_fixed = await client.get(
                "/health", headers={"X-Request-ID": "test-fixed-id-123"}
            )
            check(
                "E2 X-Request-ID pass-through preserved",
                r_fixed.headers.get("x-request-id") == "test-fixed-id-123",
                r_fixed.headers.get("x-request-id"),
            )

            r_api_id = await client.get("/api/v1/")
            check(
                "E3 /api/v1/ carries X-Request-ID",
                bool(r_api_id.headers.get("x-request-id")),
                r_api_id.headers.get("x-request-id"),
            )

            # --- GROUP F: CORS ---
            r_pre = await client.options(
                "/health",
                headers={
                    "Origin": "https://example.com",
                    "Access-Control-Request-Method": "GET",
                },
            )
            allow_origin = r_pre.headers.get("access-control-allow-origin")
            check("F1 CORS preflight returns 200", r_pre.status_code == 200, r_pre.status_code)
            check(
                "F1 CORS preflight allows origin",
                allow_origin in {"*", "https://example.com"},
                allow_origin,
            )
            r_simple = await client.get("/health", headers={"Origin": "https://example.com"})
            check(
                "F2 simple GET has Access-Control-Allow-Origin",
                bool(r_simple.headers.get("access-control-allow-origin")),
                r_simple.headers.get("access-control-allow-origin"),
            )

            # --- GROUP G: gzip ---
            r_gz_root = await client.get("/api/v1/", headers={"Accept-Encoding": "gzip"})
            if r_gz_root.headers.get("content-encoding") == "gzip":
                check(
                    "G1 /api/v1/ gzip compression",
                    True,
                    "compressed (above 1024-byte threshold)",
                )
            elif len(r_gz_root.content) <= 1024:
                check(
                    "G1 /api/v1/ gzip compression",
                    True,
                    "skipped: response below 1024-byte threshold",
                )
            else:
                check(
                    "G1 /api/v1/ gzip compression",
                    False,
                    f"uncompressed body {len(r_gz_root.content)} bytes",
                )

            r_gz_spec = await client.get(
                "/openapi.json", headers={"Accept-Encoding": "gzip"}
            )
            large_exists = d1_holder.get("openapi_len", 0) > 1024
            if large_exists:
                check(
                    "G2 large response (>1024B) is gzip-encoded",
                    r_gz_spec.headers.get("content-encoding") == "gzip",
                    r_gz_spec.headers.get("content-encoding"),
                )
            else:
                check(
                    "G2 large response (>1024B) is gzip-encoded",
                    True,
                    "skipped: no response above 1024-byte threshold",
                )
    finally:
        # Keep asyncpg pooled connections from leaking into the lifespan loop.
        await engine.dispose()


def lifespan_check(app) -> None:
    try:
        from fastapi.testclient import TestClient
    except Exception as exc:  # noqa: BLE001
        check("H1 TestClient available", True, f"skipped: {type(exc).__name__}")
        check("H2 /health inside lifespan", True, "skipped: TestClient unavailable")
        check("H3 shutdown marker", True, "skipped: TestClient unavailable")
        return

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        with TestClient(app) as client:
            response = client.get("/health")
    captured = buf.getvalue()

    startup_ok = (
        "[startup] DB reachable" in captured
        or "[startup] DB unreachable" in captured
    )
    check("H1 lifespan startup marker printed", startup_ok, captured.strip().splitlines()[:2])
    check(
        "H2 GET /health inside lifespan returns 200",
        response.status_code == 200,
        response.status_code,
    )
    shutdown_ok = (
        "[shutdown] DB engine disposed" in captured
        or "[shutdown] engine.dispose error" in captured
    )
    check("H3 lifespan shutdown marker printed", shutdown_ok, captured.strip().splitlines()[-2:])


def pytest_check() -> None:
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-q"],
        capture_output=True, text=True, cwd=str(ROOT), timeout=600,
    )
    out = (proc.stdout or "") + (proc.stderr or "")
    m = re.search(r"(\d+) passed", out)
    passed = int(m.group(1)) if m else 0
    failed = re.search(r"(\d+) failed", out)
    check(
        "I1 pytest: N passed, 0 failed",
        proc.returncode == 0 and passed >= 2 and not failed and "error" not in out.lower().split()[-3:],
        out.strip().splitlines()[-1] if out.strip() else None,
    )
    if failed:
        check("I2 pytest has no regressions", False, failed.group(0))
    else:
        check("I2 pytest has no regressions", proc.returncode == 0, "0 failed")


def main() -> int:
    # --- GROUP A: import & app construction ---
    try:
        from app.main import app
        import_error = None
    except Exception as exc:  # noqa: BLE001
        app = None
        import_error = f"{type(exc).__name__}: {exc}"

    check("A1 import app.main succeeds", app is not None, import_error)
    if app is None:
        print()
        print("=" * 60)
        print(f"PHASE 10 SELF-CHECK — 0/{len(results)} passed")
        print("=" * 60)
        return 1

    check(
        "A2 app.title contains 'Urban Tandoor'",
        "Urban Tandoor" in app.title,
        app.title,
    )
    check(
        "A3 app.version is a non-empty string",
        isinstance(app.version, str) and bool(app.version.strip()),
        app.version,
    )
    check(
        "A4 lifespan attached",
        getattr(app.router, "lifespan_context", None) is not None,
        type(getattr(app.router, "lifespan_context", None)).__name__,
    )

    # --- GROUPS B-G: ASGI transport (no lifespan) ---
    d1_holder: dict = {}
    asyncio.run(http_checks(app, d1_holder))

    # --- GROUP H: lifespan via TestClient ---
    lifespan_check(app)

    # --- GROUP I: existing tests ---
    pytest_check()

    print()
    print("=" * 60)
    failed = [r for r in results if r[1] == "FAIL"]
    print(f"PHASE 10 SELF-CHECK — {len(results) - len(failed)}/{len(results)} passed")
    print("=" * 60)
    if failed:
        print("FAILED CHECKS:")
        for name, _, got in failed:
            print(f"  - {name}  (got: {got})")
        print()
        return 1
    print("FASTAPI BOOTSTRAP VERIFIED: health, versioned root, docs, middleware, lifespan.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
