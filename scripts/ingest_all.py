"""
Unified ingestion CLI for the Urban Tandoor pipeline.

Usage:
  python scripts/ingest_all.py [--only DOMAIN ...] [--strict] [--wipe [--yes]]

Domains: menu, inventory, docs
JSON summary printed to STDOUT. Human progress printed to STDERR.
Exit codes: 0 = all ok, 1 = any error (or wipe-safety-gate refused),
            2 = argparse error.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from datetime import datetime, timezone
from typing import Awaitable, Callable

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session_factory, engine
from app.ingestion.docs_pipeline import ingest_all_docs
from app.ingestion.excel_inventory import ingest_inventory
from app.ingestion.excel_menu import ingest_menu_catalog

DOMAINS = ("menu", "inventory", "docs")

# All 20 business tables. Order for TRUNCATE doesn't matter with CASCADE
# since all FK targets are in the list.
ALL_TABLES = [
    "suppliers", "ingredients", "branches", "branch_stock", "recipes",
    "stock_movements", "categories", "menu_items", "variants", "addons",
    "item_addons", "item_aliases", "branch_menu", "inventory_links",
    "deals", "deal_items", "allergen_guide", "service_rules",
    "source_documents", "document_chunks",
]


async def _wipe_all(session: AsyncSession) -> None:
    """TRUNCATE all 20 business tables atomically. Does not touch alembic_version."""
    stmt = f"TRUNCATE TABLE {', '.join(ALL_TABLES)} RESTART IDENTITY CASCADE"
    await session.execute(text(stmt))
    await session.commit()


async def _run_domain(
    name: str,
    ingest_fn: Callable[[AsyncSession], Awaitable[dict]],
    *,
    strict: bool,
) -> dict:
    """Run one domain. Each domain gets its own session/commit so --strict=False
    yields partial success. Injected failure via UTG_INJECT_FAILURE env var."""
    injected = os.environ.get("UTG_INJECT_FAILURE", "").strip().lower()
    if injected == name:
        return {
            "status": "error",
            "error": f"injected failure for {name} (UTG_INJECT_FAILURE)",
            "type": "RuntimeError",
            "duration_s": 0.0,
        }

    started = time.monotonic()
    print(f"[ingest] {name}: starting", file=sys.stderr)
    try:
        async with async_session_factory() as session:
            result = await ingest_fn(session)
            await session.commit()
        duration = time.monotonic() - started
        print(f"[ingest] {name}: ok ({duration:.2f}s)", file=sys.stderr)
        # result may be dict of counts (menu/inventory) or dict of
        # {profile: {...}, menu_narratives: {...}} (docs)
        return {"status": "ok", "result": result, "duration_s": round(duration, 2)}
    except Exception as exc:  # noqa: BLE001
        duration = time.monotonic() - started
        print(f"[ingest] {name}: ERROR {type(exc).__name__}: {exc}", file=sys.stderr)
        return {
            "status": "error",
            "error": str(exc),
            "type": type(exc).__name__,
            "duration_s": round(duration, 2),
        }


async def _main(args: argparse.Namespace) -> int:
    started = time.monotonic()

    # --- Safety gate for --wipe ---
    if args.wipe and not args.yes:
        print(
            "[ingest] --wipe requires --yes to confirm. No data was deleted.",
            file=sys.stderr,
        )
        summary = {
            "status": "refused",
            "reason": "wipe_requires_yes",
            "started_at": datetime.now(timezone.utc).isoformat(),
            "domains_requested": args.only or list(DOMAINS),
        }
        print(json.dumps(summary, indent=2))
        return 1

    domains = args.only or list(DOMAINS)

    # --- Wipe if requested ---
    if args.wipe:
        print("[ingest] wiping all 20 business tables...", file=sys.stderr)
        async with async_session_factory() as session:
            await _wipe_all(session)
        print("[ingest] wipe complete", file=sys.stderr)

    # --- Domain dispatch ---
    ingest_fns = {
        "menu": ingest_menu_catalog,
        "inventory": ingest_inventory,
        "docs": ingest_all_docs,
    }

    summary: dict = {
        "status": "ok",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "domains_requested": domains,
        "domains": {},
        "errors": [],
    }

    for name in domains:
        r = await _run_domain(name, ingest_fns[name], strict=args.strict)
        summary["domains"][name] = r
        if r["status"] == "error":
            summary["errors"].append({"domain": name, **{k: r[k] for k in ("error", "type")}})
            if args.strict:
                print(
                    f"[ingest] strict mode: aborting after {name} failure",
                    file=sys.stderr,
                )
                break

    summary["duration_s"] = round(time.monotonic() - started, 2)
    summary["finished_at"] = datetime.now(timezone.utc).isoformat()
    if summary["errors"]:
        summary["status"] = "partial" if not args.strict else "failed"

    print(json.dumps(summary, indent=2, default=str))
    return 0 if summary["status"] == "ok" else 1


async def _run_and_dispose(args: argparse.Namespace) -> int:
    """Run the pipeline and dispose the engine on the same event loop.

    The engine's asyncpg pool is bound to the loop it was created on; disposing
    it from a second ``asyncio.run`` would try to close pooled connections from
    a different loop. Keeping both in one coroutine is behaviourally identical
    to the original two-run form and avoids spurious loop errors.
    """
    try:
        return await _main(args)
    finally:
        await engine.dispose()


def cli(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="utg-ingest",
        description="Urban Tandoor unified ingestion pipeline.",
    )
    parser.add_argument(
        "--only", action="append", choices=DOMAINS, default=None,
        help="Run only the specified domain(s). Repeatable: --only menu --only docs",
    )
    parser.add_argument(
        "--strict", action="store_true",
        help="Abort on first domain failure (default: continue, mark partial)",
    )
    parser.add_argument(
        "--wipe", action="store_true",
        help="DANGER: TRUNCATE all 20 business tables before ingesting. "
             "Requires --yes to confirm.",
    )
    parser.add_argument(
        "--yes", action="store_true",
        help="Confirm --wipe without interactive prompt.",
    )
    args = parser.parse_args(argv)
    rc = asyncio.run(_run_and_dispose(args))
    return rc


if __name__ == "__main__":
    sys.exit(cli())
