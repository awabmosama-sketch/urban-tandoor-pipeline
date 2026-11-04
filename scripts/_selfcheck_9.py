"""
Self-check for Phase 9 (unified ingestion CLI).

Run: python -m uv run python scripts/_selfcheck_9.py
Exits 0 on success, 1 on failure.

Every ingestion run is executed as a subprocess against the REAL
``utg-ingest`` console script so argparse, stdout/JSON discipline and exit
codes are all exercised end-to-end. DB comparisons use one persistent event
loop so the asyncpg pool never crosses loops.
"""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from sqlalchemy import text

from app.database import async_session_factory, engine

ROOT = Path(__file__).resolve().parents[1]

TABLES = [
    "suppliers", "ingredients", "branches", "branch_stock", "recipes",
    "stock_movements", "categories", "menu_items", "variants", "addons",
    "item_addons", "item_aliases", "branch_menu", "inventory_links",
    "deals", "deal_items", "allergen_guide", "service_rules",
    "source_documents", "document_chunks",
]

EXPECTED_BASELINE = {
    "suppliers": 7, "ingredients": 60, "branches": 2, "branch_stock": 120,
    "recipes": 130, "stock_movements": 8, "categories": 8, "menu_items": 118,
    "variants": 148, "addons": 10, "item_addons": 284, "item_aliases": 158,
    "branch_menu": 236, "inventory_links": 236, "deals": 6, "deal_items": 15,
    "allergen_guide": 8, "service_rules": 7, "source_documents": 2,
    "document_chunks": 128,
}

RUN_SUMMARY_KEYS = {
    "status", "started_at", "domains_requested", "domains", "errors",
    "duration_s", "finished_at",
}

_exe = shutil.which("utg-ingest")
CMD = [_exe] if _exe else [sys.executable, str(ROOT / "scripts" / "ingest_all.py")]

results: list[tuple[str, str, object]] = []
json_summaries: list[tuple[str, dict]] = []

_LOOP = asyncio.new_event_loop()


def check(name: str, condition: bool, got=None) -> None:
    status = "PASS" if condition else "FAIL"
    results.append((name, status, got))
    print(f"{status}  {name}" + ("" if got is None else f"  (got: {got})"))


def run_cli(*args: str, inject: str | None = None) -> subprocess.CompletedProcess:
    env = {
        **os.environ,
        "APP_ENV": "test",          # keep SQL echo out of stdout
        "PYTHONIOENCODING": "utf-8",
    }
    env.pop("UTG_INJECT_FAILURE", None)
    if inject:
        env["UTG_INJECT_FAILURE"] = inject
    return subprocess.run(
        [*CMD, *args],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        cwd=str(ROOT), env=env, timeout=600,
    )


def parse_json(proc: subprocess.CompletedProcess):
    try:
        return json.loads(proc.stdout)
    except Exception:
        return None


async def _counts_async() -> dict[str, int]:
    async with async_session_factory() as session:
        out = {}
        for t in TABLES:
            out[t] = int(
                (await session.execute(text(f"SELECT count(*) FROM {t}"))).scalar()
            )
        return out


def counts() -> dict[str, int]:
    return _LOOP.run_until_complete(_counts_async())


def diff_counts(actual: dict[str, int], expected: dict[str, int]) -> dict[str, tuple]:
    return {k: (expected.get(k), actual.get(k)) for k in TABLES if actual.get(k) != expected.get(k)}


def last_stderr_line(proc: subprocess.CompletedProcess) -> str:
    lines = [ln for ln in (proc.stderr or "").strip().splitlines() if ln.strip()]
    return lines[-1][:200] if lines else ""


def main() -> int:
    # --- GROUP A: CLI surface + baseline ---
    baseline = counts()
    check(
        "baseline: all 20 table counts match Phase 6/7/8",
        baseline == EXPECTED_BASELINE and all(v > 0 for v in baseline.values()),
        diff_counts(baseline, EXPECTED_BASELINE) or "20/20 non-zero",
    )

    p_help = run_cli("--help")
    help_text = (p_help.stdout or "") + (p_help.stderr or "")
    check("A1 utg-ingest --help exits 0", p_help.returncode == 0, p_help.returncode)
    check(
        "A1 help lists --only/--strict/--wipe/--yes",
        all(flag in help_text for flag in ("--only", "--strict", "--wipe", "--yes")),
        [f for f in ("--only", "--strict", "--wipe", "--yes") if f not in help_text] or "all present",
    )

    p_bad = run_cli("--only", "garbage")
    check(
        "A2 --only garbage exits 2 (argparse)",
        p_bad.returncode == 2,
        p_bad.returncode,
    )

    p_refuse = run_cli("--wipe")
    refuse = parse_json(p_refuse)
    if refuse is not None:
        json_summaries.append(("A3 --wipe without --yes", refuse))
    check(
        "A3 --wipe without --yes exits 1",
        p_refuse.returncode == 1,
        p_refuse.returncode,
    )
    check(
        "A3 refusal JSON: status=refused, reason=wipe_requires_yes",
        bool(refuse)
        and refuse.get("status") == "refused"
        and refuse.get("reason") == "wipe_requires_yes",
        None if not refuse else (refuse.get("status"), refuse.get("reason")),
    )
    check(
        "A3 refusal did not modify data",
        counts() == baseline,
        diff_counts(counts(), baseline) or "unchanged",
    )

    # --- GROUP B: selective execution ---
    p_menu = run_cli("--only", "menu")
    menu_json = parse_json(p_menu)
    if menu_json is not None:
        json_summaries.append(("B1 --only menu", menu_json))
    check("B1 --only menu exits 0", p_menu.returncode == 0, p_menu.returncode)
    check(
        "B1 --only menu JSON: status=ok, only menu domain",
        bool(menu_json)
        and menu_json.get("status") == "ok"
        and set(menu_json.get("domains", {})) == {"menu"}
        and menu_json["domains"]["menu"].get("status") == "ok",
        None if not menu_json else (menu_json.get("status"), sorted(menu_json.get("domains", {}))),
    )
    b2 = counts()
    check(
        "B2 menu re-run is idempotent (counts == baseline)",
        b2 == baseline,
        diff_counts(b2, baseline) or "unchanged",
    )

    p_docs = run_cli("--only", "docs")
    docs_json = parse_json(p_docs)
    if docs_json is not None:
        json_summaries.append(("B3 --only docs", docs_json))
    docs_result = (docs_json or {}).get("domains", {}).get("docs", {}).get("result", {})
    check("B3 --only docs exits 0", p_docs.returncode == 0, p_docs.returncode)
    check(
        "B3 docs profile + menu_narratives skipped (checksums unchanged)",
        docs_result.get("profile", {}).get("status") == "skipped"
        and docs_result.get("menu_narratives", {}).get("status") == "skipped",
        None if not docs_result else {
            "profile": docs_result.get("profile", {}).get("status"),
            "menu_narratives": docs_result.get("menu_narratives", {}).get("status"),
        },
    )

    # --- GROUP C: full run idempotency ---
    p_full = run_cli()
    full1 = parse_json(p_full)
    if full1 is not None:
        json_summaries.append(("C1 full run", full1))
    check("C1 full run exits 0", p_full.returncode == 0, p_full.returncode)
    check(
        "C1 full run JSON: status=ok, all 3 domains ok",
        bool(full1)
        and full1.get("status") == "ok"
        and set(full1.get("domains", {})) == {"menu", "inventory", "docs"}
        and all(d.get("status") == "ok" for d in full1["domains"].values()),
        None if not full1 else {
            k: v.get("status") for k, v in full1.get("domains", {}).items()
        },
    )
    c2 = counts()
    check(
        "C2 full run counts == baseline",
        c2 == baseline,
        diff_counts(c2, baseline) or "identical",
    )

    p_full2 = run_cli()
    full2 = parse_json(p_full2)
    if full2 is not None:
        json_summaries.append(("C3 full run (repeat)", full2))
    shape1 = None if not full1 else {
        k: v.get("status") for k, v in full1.get("domains", {}).items()
    }
    shape2 = None if not full2 else {
        k: v.get("status") for k, v in full2.get("domains", {}).items()
    }
    check(
        "C3 repeat full run: same JSON structure and counts",
        p_full2.returncode == 0
        and shape2 == shape1
        and (full2 or {}).get("status") == "ok"
        and counts() == baseline,
        None if shape2 is None else (shape2, diff_counts(counts(), baseline) or "identical"),
    )

    # --- GROUP D: injected failure, strict ---
    p_strict = run_cli(
        "--only", "menu", "--only", "inventory", "--only", "docs", "--strict",
        inject="inventory",
    )
    strict_json = parse_json(p_strict)
    if strict_json is not None:
        json_summaries.append(("D1 strict + injected failure", strict_json))
    sdom = (strict_json or {}).get("domains", {})
    check(
        "D1 strict injected run exits 1",
        p_strict.returncode == 1,
        (p_strict.returncode, last_stderr_line(p_strict)),
    )
    check(
        "D1 strict: status=failed, aborted after inventory",
        bool(strict_json)
        and strict_json.get("status") == "failed"
        and set(sdom) == {"menu", "inventory"},
        None if not strict_json else (strict_json.get("status"), sorted(sdom)),
    )
    check(
        "D1 strict: menu ok, inventory error",
        sdom.get("menu", {}).get("status") == "ok"
        and sdom.get("inventory", {}).get("status") == "error",
        None if not sdom else {k: v.get("status") for k, v in sdom.items()},
    )
    d2 = counts()
    check(
        "D2 strict injected run left DB at baseline",
        d2 == baseline,
        diff_counts(d2, baseline) or "unchanged",
    )

    # --- GROUP E: injected failure, non-strict ---
    p_loose = run_cli(
        "--only", "menu", "--only", "inventory", "--only", "docs",
        inject="inventory",
    )
    loose_json = parse_json(p_loose)
    if loose_json is not None:
        json_summaries.append(("E1 non-strict + injected failure", loose_json))
    ldom = (loose_json or {}).get("domains", {})
    check(
        "E1 non-strict injected run exits 1",
        p_loose.returncode == 1,
        (p_loose.returncode, last_stderr_line(p_loose)),
    )
    check(
        "E1 non-strict: status=partial, all 3 domains present",
        bool(loose_json)
        and loose_json.get("status") == "partial"
        and set(ldom) == {"menu", "inventory", "docs"},
        None if not loose_json else (loose_json.get("status"), sorted(ldom)),
    )
    check(
        "E1 non-strict: menu ok, inventory error, docs ok",
        ldom.get("menu", {}).get("status") == "ok"
        and ldom.get("inventory", {}).get("status") == "error"
        and ldom.get("docs", {}).get("status") == "ok",
        None if not ldom else {k: v.get("status") for k, v in ldom.items()},
    )
    e2 = counts()
    check(
        "E2 non-strict injected run left DB at baseline",
        e2 == baseline,
        diff_counts(e2, baseline) or "unchanged",
    )

    # --- GROUP F: wipe + full restore ---
    p_wipe = run_cli("--wipe", "--yes")
    wipe_json = parse_json(p_wipe)
    if wipe_json is not None:
        json_summaries.append(("F2 --wipe --yes", wipe_json))
    wdom = (wipe_json or {}).get("domains", {})
    check(
        "F2 --wipe --yes exits 0",
        p_wipe.returncode == 0,
        (p_wipe.returncode, last_stderr_line(p_wipe)),
    )
    check(
        "F2 wipe run: status=ok, all 3 domains ok",
        bool(wipe_json)
        and wipe_json.get("status") == "ok"
        and set(wdom) == {"menu", "inventory", "docs"}
        and all(d.get("status") == "ok" for d in wdom.values()),
        None if not wipe_json else {
            k: v.get("status") for k, v in wdom.items()
        },
    )

    f3 = counts()
    f3_diff = diff_counts(f3, baseline)
    if f3_diff:
        # One self-heal attempt per the phase spec: every domain is idempotent.
        print(f"[selfcheck] F3 mismatch, re-running full ingest once: {f3_diff}", file=sys.stderr)
        run_cli()
        f3 = counts()
        f3_diff = diff_counts(f3, baseline)
    check(
        "F3 wipe + re-ingest round-trips all 20 tables to baseline",
        not f3_diff,
        f3_diff or "identical",
    )

    # --- GROUP G: JSON output validity ---
    for label, payload in json_summaries:
        if payload.get("status") == "refused":
            ok = {"status", "reason", "started_at", "domains_requested"} <= set(payload)
            check(f"G {label}: refused JSON keys", ok, sorted(payload))
        else:
            missing = RUN_SUMMARY_KEYS - set(payload)
            check(
                f"G {label}: JSON parses with full summary schema",
                not missing,
                sorted(missing) or "all keys present",
            )

    # --- GROUP H: pytest ---
    p_test = subprocess.run(
        [sys.executable, "-m", "pytest", "-q"],
        capture_output=True, text=True, cwd=str(ROOT), timeout=600,
    )
    test_out = (p_test.stdout or "") + (p_test.stderr or "")
    check(
        "H1 pytest reports 2 passed",
        p_test.returncode == 0 and "2 passed" in test_out,
        test_out.strip().splitlines()[-1] if test_out.strip() else None,
    )

    print()
    print("=" * 60)
    failed = [r for r in results if r[1] == "FAIL"]
    print(f"PHASE 9 SELF-CHECK — {len(results) - len(failed)}/{len(results)} passed")
    print("=" * 60)
    if failed:
        print("FAILED CHECKS:")
        for name, _, got in failed:
            print(f"  - {name}  (got: {got})")
        print()
        return 1
    print("UNIFIED CLI VERIFIED: selective runs, strict/partial, wipe+restore, JSON discipline.")
    return 0


if __name__ == "__main__":
    try:
        rc = main()
    finally:
        try:
            _LOOP.run_until_complete(engine.dispose())
        finally:
            _LOOP.close()
    sys.exit(rc)
