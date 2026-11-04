"""
Self-check for Phase 13 (admin refresh endpoints).

Run: python -m uv run python scripts/_selfcheck_13.py
Exits 0 on success, 1 on failure.

Only reads the DB directly for verification; ingestion writes happen
exclusively through the admin refresh endpoints.
"""
from __future__ import annotations

import asyncio
import re
import subprocess
import sys
import traceback
from pathlib import Path

import httpx
from sqlalchemy import text

from app.config import get_settings
from app.database import async_session_factory, engine
from app.main import app
from app.services.jobs import get_job_store, reset_job_store

ROOT = Path(__file__).resolve().parents[1]

ADMIN_HEADERS = {"X-Admin-Token": "change-me"}
WRONG_HEADERS = {"X-Admin-Token": "wrong-token"}

TABLES = [
    "suppliers", "ingredients", "branches", "branch_stock", "recipes",
    "stock_movements", "categories", "menu_items", "variants", "addons",
    "item_addons", "item_aliases", "branch_menu", "inventory_links",
    "deals", "deal_items", "allergen_guide", "service_rules",
    "source_documents", "document_chunks",
]

ADMIN_ENDPOINT_KEYS = {"admin_refresh", "admin_job_detail", "admin_jobs_list"}

MENU_KEYS = {
    "categories", "menu_items", "variants", "addons", "item_addons",
    "item_aliases", "branch_menu", "inventory_links", "deals",
    "deal_items", "allergen_guide", "service_rules",
}
INVENTORY_KEYS = {
    "suppliers", "ingredients", "branches", "branch_stock",
    "recipes", "stock_movements",
}
JOB_FIELDS = {
    "job_id", "domain", "status", "created_at", "started_at",
    "finished_at", "result", "error",
}

results: list[tuple[str, str, object]] = []


def check(name: str, condition: bool, got=None) -> None:
    status = "PASS" if condition else "FAIL"
    results.append((name, status, got))
    print(f"{status}  {name}" + ("" if got is None else f"  (got: {got})"))


def run_pytest() -> tuple[int, str]:
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-q"],
        capture_output=True, text=True, cwd=str(ROOT), timeout=600,
    )
    out = (proc.stdout or "") + (proc.stderr or "")
    m = re.search(r"(\d+) passed", out)
    passed = int(m.group(1)) if m else 0
    return passed, out.strip().splitlines()[-1] if out.strip() else ""


async def db_counts() -> dict[str, int]:
    async with async_session_factory() as session:
        return {
            t: int((await session.execute(text(f"SELECT COUNT(*) FROM {t}"))).scalar())
            for t in TABLES
        }


async def jget(client: httpx.AsyncClient, path: str, headers=None, **params):
    resp = await client.get(path, headers=headers, params=params or None)
    try:
        body = resp.json()
    except Exception:  # noqa: BLE001
        body = None
    return resp, body


async def jpost(client: httpx.AsyncClient, path: str, headers=None, payload=None):
    resp = await client.post(path, headers=headers, json=payload)
    try:
        body = resp.json()
    except Exception:  # noqa: BLE001
        body = None
    return resp, body


async def get_job(client: httpx.AsyncClient, job_id: str) -> dict:
    r, data = await jget(
        client, f"/api/v1/admin/jobs/{job_id}", headers=ADMIN_HEADERS,
    )
    if r.status_code != 200 or not isinstance(data, dict):
        raise AssertionError(f"job fetch failed: {r.status_code} {data}")
    return data


async def wait_for_job(
    client: httpx.AsyncClient, job_id: str, timeout: float = 120.0,
) -> dict:
    loop = asyncio.get_running_loop()
    start = loop.time()
    while loop.time() - start < timeout:
        data = await get_job(client, job_id)
        if data["status"] in ("success", "error"):
            return data
        await asyncio.sleep(0.1)
    raise TimeoutError(f"job {job_id} did not complete in {timeout}s")


async def checks(pytest_passed: int, pytest_tail: str) -> None:
    transport = httpx.ASGITransport(app=app)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            # --- GROUP A: setup ---
            baseline = await db_counts()
            check(
                "A1 DB baseline: all 20 tables non-zero",
                len(baseline) == 20 and all(v > 0 for v in baseline.values()),
                baseline,
            )
            check(
                "A2 pytest: 2+ passed, 0 failed",
                pytest_passed >= 2 and "failed" not in pytest_tail,
                pytest_tail,
            )
            reset_job_store()
            store = get_job_store()
            check(
                "A3 job store reset to empty",
                await store.list_recent(limit=1) == [],
                "empty",
            )

            # --- GROUP B: auth ---
            r, _ = await jpost(client, "/api/v1/admin/refresh/menu")
            check(
                "B1 POST refresh/menu without token -> 422 or 401",
                r.status_code in (422, 401),
                r.status_code,
            )
            r, _ = await jpost(
                client, "/api/v1/admin/refresh/menu", headers=WRONG_HEADERS,
            )
            check(
                "B2 POST refresh/menu wrong token -> 401",
                r.status_code == 401,
                r.status_code,
            )
            r, b3 = await jpost(
                client, "/api/v1/admin/refresh/menu", headers=ADMIN_HEADERS,
            )
            check(
                "B3 POST refresh/menu correct token -> not 401 (202)",
                r.status_code != 401 and r.status_code == 202,
                r.status_code,
            )
            r, _ = await jget(client, "/api/v1/admin/jobs")
            check(
                "B4 GET admin/jobs without token -> 422 or 401",
                r.status_code in (422, 401),
                r.status_code,
            )
            r, _ = await jget(
                client, "/api/v1/admin/jobs/anything", headers=ADMIN_HEADERS,
            )
            check(
                "B5 GET admin/jobs/<unknown> with token -> 404",
                r.status_code == 404,
                r.status_code,
            )
            if isinstance(b3, dict) and b3.get("job_id"):
                await wait_for_job(client, b3["job_id"])

            # --- GROUP C: menu refresh ---
            r, c1 = await jpost(
                client, "/api/v1/admin/refresh/menu", headers=ADMIN_HEADERS,
            )
            check("C1 POST refresh/menu -> 202", r.status_code == 202, r.status_code)
            c1 = c1 or {}
            check(
                "C2 response has job_id/domain/status",
                {"job_id", "domain", "status"} <= set(c1),
                sorted(c1),
            )
            check("C3 response.status == 'pending'", c1.get("status") == "pending", c1.get("status"))
            check("C4 response.domain == 'menu'", c1.get("domain") == "menu", c1.get("domain"))
            c_job = await wait_for_job(client, c1.get("job_id", ""))
            check("C5 polled job reaches success", c_job.get("status") == "success", c_job.get("status"))
            c_result = c_job.get("result") or {}
            check(
                "C6 job.result has menu counts",
                isinstance(c_result, dict) and MENU_KEYS <= set(c_result),
                sorted(c_result) if isinstance(c_result, dict) else c_result,
            )
            check(
                "C7 started_at and finished_at are set",
                bool(c_job.get("started_at")) and bool(c_job.get("finished_at")),
                (c_job.get("started_at"), c_job.get("finished_at")),
            )
            try:
                started_ok = c_job.get("started_at") <= c_job.get("finished_at")
            except TypeError:
                started_ok = False
            check("C8 started_at <= finished_at", bool(started_ok), started_ok)
            check("C9 job.error is None", c_job.get("error") is None, c_job.get("error"))
            check(
                "C10 DB counts unchanged after menu refresh",
                await db_counts() == baseline,
                "unchanged",
            )

            # --- GROUP D: inventory refresh ---
            r, d1 = await jpost(
                client, "/api/v1/admin/refresh/inventory", headers=ADMIN_HEADERS,
            )
            check("D1 POST refresh/inventory -> 202", r.status_code == 202, r.status_code)
            d_job = await wait_for_job(client, (d1 or {}).get("job_id", ""))
            check("D2 inventory job reaches success", d_job.get("status") == "success", d_job.get("status"))
            d_result = d_job.get("result") or {}
            check(
                "D3 job.result has inventory counts",
                isinstance(d_result, dict) and INVENTORY_KEYS <= set(d_result),
                sorted(d_result) if isinstance(d_result, dict) else d_result,
            )
            check(
                "D4 job.result.branch_stock == 120",
                d_result.get("branch_stock") == 120,
                d_result.get("branch_stock"),
            )
            check(
                "D5 DB counts unchanged after inventory refresh",
                await db_counts() == baseline,
                "unchanged",
            )

            # --- GROUP E: docs refresh ---
            r, e1 = await jpost(
                client, "/api/v1/admin/refresh/docs", headers=ADMIN_HEADERS,
            )
            check("E1 POST refresh/docs -> 202", r.status_code == 202, r.status_code)
            e_job = await wait_for_job(client, (e1 or {}).get("job_id", ""))
            check("E2 docs job reaches success", e_job.get("status") == "success", e_job.get("status"))
            e_result = e_job.get("result") or {}
            check(
                "E3 job.result has profile and menu_narratives",
                isinstance(e_result, dict) and {"profile", "menu_narratives"} <= set(e_result),
                sorted(e_result) if isinstance(e_result, dict) else e_result,
            )
            prof_status = (e_result.get("profile") or {}).get("status")
            menu_status = (e_result.get("menu_narratives") or {}).get("status")
            check(
                "E4 both docs skipped (checksums unchanged)",
                prof_status == "skipped" and menu_status == "skipped",
                (prof_status, menu_status),
            )
            check(
                "E5 DB counts unchanged after docs refresh",
                await db_counts() == baseline,
                "unchanged",
            )

            # --- GROUP F: refresh all ---
            r, f1 = await jpost(
                client, "/api/v1/admin/refresh/all", headers=ADMIN_HEADERS,
            )
            check("F1 POST refresh/all -> 202", r.status_code == 202, r.status_code)
            f_job = await wait_for_job(client, (f1 or {}).get("job_id", ""))
            check("F2 all-domains job reaches success", f_job.get("status") == "success", f_job.get("status"))
            f_result = f_job.get("result") or {}
            check(
                "F3 job.result has menu/inventory/docs",
                isinstance(f_result, dict) and {"menu", "inventory", "docs"} <= set(f_result),
                sorted(f_result) if isinstance(f_result, dict) else f_result,
            )
            check(
                "F4 every sub-result is a dict",
                isinstance(f_result, dict)
                and all(isinstance(f_result.get(k), dict) for k in ("menu", "inventory", "docs")),
                {k: type(f_result.get(k)).__name__ for k in ("menu", "inventory", "docs")},
            )
            check(
                "F5 started/finished form a real non-negative span",
                bool(f_job.get("started_at"))
                and bool(f_job.get("finished_at"))
                and f_job.get("started_at") <= f_job.get("finished_at"),
                (f_job.get("started_at"), f_job.get("finished_at")),
            )
            check(
                "F6 DB counts unchanged after refresh/all",
                await db_counts() == baseline,
                "unchanged",
            )

            # --- GROUP G: unknown domain ---
            r, g1 = await jpost(
                client, "/api/v1/admin/refresh/garbage", headers=ADMIN_HEADERS,
            )
            check("G1 POST refresh/garbage -> 400", r.status_code == 400, r.status_code)
            detail = (g1 or {}).get("detail") if isinstance(g1, dict) else ""
            detail = str(detail)
            check(
                "G2 detail mentions valid domains",
                all(d in detail for d in ("menu", "inventory", "docs", "all")),
                detail[:120],
            )

            # --- GROUP H: job list ---
            r, h1 = await jget(
                client, "/api/v1/admin/jobs", headers=ADMIN_HEADERS,
            )
            h1 = h1 or []
            check("H1 GET admin/jobs -> 200", r.status_code == 200, r.status_code)
            check("H2 job list length >= 5", len(h1) >= 5, len(h1))
            check(
                "H3 every job has all required fields",
                bool(h1) and all(JOB_FIELDS <= set(j) for j in h1),
                "all jobs" if h1 else "empty",
            )
            r, h4 = await jget(
                client, "/api/v1/admin/jobs", headers=ADMIN_HEADERS, limit=3,
            )
            check(
                "H4 GET admin/jobs?limit=3 -> <= 3",
                r.status_code == 200 and len(h4 or []) <= 3,
                (r.status_code, len(h4 or [])),
            )
            r, _ = await jget(
                client, "/api/v1/admin/jobs", headers=ADMIN_HEADERS, limit=0,
            )
            check("H5 GET admin/jobs?limit=0 -> 400", r.status_code == 400, r.status_code)
            r, _ = await jget(
                client, "/api/v1/admin/jobs", headers=ADMIN_HEADERS, limit=101,
            )
            check("H6 GET admin/jobs?limit=101 -> 400", r.status_code == 400, r.status_code)

            # --- GROUP I: concurrency ---
            responses = await asyncio.gather(*[
                client.post(
                    "/api/v1/admin/refresh/menu", headers=ADMIN_HEADERS,
                )
                for _ in range(3)
            ])
            i_ids = [
                (resp.json().get("job_id") if resp.status_code == 202 else None)
                for resp in responses
            ]
            check(
                "I1-I2 3 parallel refresh/menu -> all 202",
                all(resp.status_code == 202 for resp in responses),
                [resp.status_code for resp in responses],
            )
            check(
                "I3 all 3 job_ids are different",
                all(i_ids) and len(set(i_ids)) == 3,
                i_ids,
            )
            i_jobs = await asyncio.gather(*[
                wait_for_job(client, jid) for jid in i_ids if jid
            ])
            check(
                "I4 all 3 concurrent jobs succeed",
                len(i_jobs) == 3 and all(j.get("status") == "success" for j in i_jobs),
                [j.get("status") for j in i_jobs],
            )
            check(
                "I5 DB counts unchanged after 3 concurrent refreshes",
                await db_counts() == baseline,
                "unchanged",
            )

            # --- GROUP J: lifecycle observation ---
            r, j1 = await jpost(
                client, "/api/v1/admin/refresh/menu", headers=ADMIN_HEADERS,
            )
            jid = (j1 or {}).get("job_id", "")
            first = await get_job(client, jid)
            check(
                "J1 immediate poll status in {pending,running,success}",
                first.get("status") in ("pending", "running", "success"),
                first.get("status"),
            )
            sequence = [first.get("status")]
            rank = {"pending": 0, "running": 1, "success": 2, "error": 2}
            loop = asyncio.get_running_loop()
            deadline = loop.time() + 120.0
            final = first
            while loop.time() < deadline:
                final = await get_job(client, jid)
                sequence.append(final.get("status"))
                if final.get("status") in ("success", "error"):
                    break
                await asyncio.sleep(0.05)
            ranks = [rank.get(s, -1) for s in sequence]
            check(
                "J2 status sequence never goes backwards",
                all(ranks[i] <= ranks[i + 1] for i in range(len(ranks) - 1)),
                sequence,
            )
            check(
                "J3 final status is success within timeout",
                final.get("status") == "success",
                final.get("status"),
            )
            running_seen = any(s in ("running", "success") for s in sequence)
            check(
                "J4 started_at set by running-or-later",
                bool(final.get("started_at")) if running_seen else True,
                final.get("started_at"),
            )
            check(
                "J5 finished_at set on success",
                final.get("status") != "success" or bool(final.get("finished_at")),
                final.get("finished_at"),
            )

            # --- GROUP K: injected auth failure ---
            settings = get_settings()
            saved = settings.admin_token
            try:
                settings.admin_token = "wrong"
                r, _ = await jpost(
                    client, "/api/v1/admin/refresh/menu", headers=ADMIN_HEADERS,
                )
                check("K2 original token rejected while admin_token='wrong'", r.status_code == 401, r.status_code)
            finally:
                settings.admin_token = saved
            r, k4 = await jpost(
                client, "/api/v1/admin/refresh/menu", headers=ADMIN_HEADERS,
            )
            check("K4 correct token accepted after restore -> 202", r.status_code == 202, r.status_code)
            if r.status_code == 202:
                await wait_for_job(client, (k4 or {}).get("job_id", ""))
            check(
                "K5 DB counts unchanged after auth tests",
                await db_counts() == baseline,
                "unchanged",
            )

            # --- GROUP L: OpenAPI ---
            r, spec = await jget(client, "/openapi.json")
            paths = (spec or {}).get("paths", {})
            refresh = paths.get("/api/v1/admin/refresh/{domain}", {})
            check(
                "L1 openapi contains /admin/refresh/{domain}",
                "/api/v1/admin/refresh/{domain}" in paths,
                None,
            )
            check(
                "L2 openapi contains /admin/jobs/{job_id}",
                "/api/v1/admin/jobs/{job_id}" in paths,
                None,
            )
            check(
                "L3 openapi contains /admin/jobs",
                "/api/v1/admin/jobs" in paths,
                None,
            )
            check(
                "L4 refresh endpoint method is post",
                "post" in refresh,
                sorted(refresh),
            )
            codes = (refresh.get("post") or {}).get("responses", {})
            check(
                "L5 refresh endpoint documents 202",
                "202" in codes,
                sorted(codes),
            )
            def token_param(op: dict) -> bool:
                return any(
                    p.get("name") == "X-Admin-Token" and p.get("required") is True
                    for p in op.get("parameters", [])
                )
            admin_ops = [
                paths.get("/api/v1/admin/refresh/{domain}", {}).get("post", {}),
                paths.get("/api/v1/admin/jobs/{job_id}", {}).get("get", {}),
                paths.get("/api/v1/admin/jobs", {}).get("get", {}),
            ]
            check(
                "L6 X-Admin-Token required on all 3 admin endpoints",
                all(token_param(op) for op in admin_ops),
                [token_param(op) for op in admin_ops],
            )

            # --- GROUP M: regression ---
            r, health = await jget(client, "/health")
            check(
                "M1 /health 200, db=ok",
                r.status_code == 200 and (health or {}).get("db") == "ok",
                (r.status_code, (health or {}).get("db")),
            )
            r, items = await jget(client, "/api/v1/menu/items")
            check(
                "M2 /menu/items == 32",
                r.status_code == 200 and len(items or []) == 32,
                len(items or []),
            )
            r, avail = await jget(
                client, "/api/v1/inventory/availability/MENU001",
                branch_id="UTG-KHI-001",
            )
            check(
                "M3 MENU001@001 max_portions == 142",
                r.status_code == 200 and (avail or {}).get("max_portions") == 142,
                (r.status_code, (avail or {}).get("max_portions")),
            )
            r, sh = await jget(client, "/api/v1/search/health")
            check(
                "M4 /search/health 200, chunks=128",
                r.status_code == 200 and (sh or {}).get("chunks_total") == 128,
                (r.status_code, (sh or {}).get("chunks_total")),
            )
            check(
                "M5 pytest: N passed, 0 failed",
                pytest_passed >= 2 and "failed" not in pytest_tail,
                pytest_tail,
            )
            r, root = await jget(client, "/api/v1/")
            endpoints = (root or {}).get("endpoints") or {}
            check(
                "M6 api_root has all 3 admin keys",
                ADMIN_ENDPOINT_KEYS <= set(endpoints),
                sorted(ADMIN_ENDPOINT_KEYS - set(endpoints)) or "all present",
            )
    finally:
        await engine.dispose()


def main() -> int:
    pytest_passed, pytest_tail = run_pytest()
    try:
        asyncio.run(checks(pytest_passed, pytest_tail))
    except Exception:  # noqa: BLE001
        print("UNEXPECTED ERROR DURING SELF-CHECK:")
        print(traceback.format_exc())
        results.append(("selfcheck harness", "FAIL", "exception"))

    print()
    print("=" * 60)
    failed = [r for r in results if r[1] == "FAIL"]
    print(f"PHASE 13 SELF-CHECK — {len(results) - len(failed)}/{len(results)} passed")
    print("=" * 60)
    if failed:
        print("FAILED CHECKS:")
        for name, _, got in failed:
            print(f"  - {name}  (got: {got})")
        print()
        return 1
    print("ADMIN REFRESH VERIFIED: auth, jobs lifecycle, concurrency, regressions.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
