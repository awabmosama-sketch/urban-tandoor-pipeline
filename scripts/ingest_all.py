"""
Unified JSON ingestion CLI for the Urban Tandoor pipeline.

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
from datetime import UTC, datetime

from app.config import get_settings
from app.database import close_db, get_db
from app.ingestion.json_ingest import (
    ingest_json_domain,
    wipe_all_collections,
)

DOMAINS = ("menu", "inventory", "docs")


async def _run_domain(name: str, *, strict: bool) -> dict:
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
        counts = await ingest_json_domain(get_db(), name)
        duration = time.monotonic() - started
        print(f"[ingest] {name}: ok ({duration:.2f}s)", file=sys.stderr)
        return {"status": "ok", "result": counts, "duration_s": round(duration, 2)}
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
    if args.json_dir:
        os.environ["JSON_DIR"] = args.json_dir
        get_settings.cache_clear()

    started = time.monotonic()

    if args.wipe and not args.yes:
        print(
            "[ingest] --wipe requires --yes to confirm. No data was deleted.",
            file=sys.stderr,
        )
        summary = {
            "status": "refused",
            "reason": "wipe_requires_yes",
            "started_at": datetime.now(UTC).isoformat(),
            "domains_requested": args.only or list(DOMAINS),
        }
        print(json.dumps(summary, indent=2))
        return 1

    domains = args.only or list(DOMAINS)

    if args.wipe:
        print("[ingest] wiping all 20 collections...", file=sys.stderr)
        deleted = await wipe_all_collections(get_db())
        print(
            f"[ingest] wipe complete ({sum(deleted.values())} documents removed)",
            file=sys.stderr,
        )

    summary: dict = {
        "status": "ok",
        "json_dir": str(get_settings().json_dir),
        "started_at": datetime.now(UTC).isoformat(),
        "domains_requested": domains,
        "domains": {},
        "errors": [],
    }

    for name in domains:
        result = await _run_domain(name, strict=args.strict)
        summary["domains"][name] = result
        if result["status"] == "error":
            summary["errors"].append(
                {"domain": name, **{k: result[k] for k in ("error", "type")}}
            )
            if args.strict:
                print(
                    f"[ingest] strict mode: aborting after {name} failure",
                    file=sys.stderr,
                )
                break

    summary["duration_s"] = round(time.monotonic() - started, 2)
    summary["finished_at"] = datetime.now(UTC).isoformat()
    if summary["errors"]:
        summary["status"] = "partial" if not args.strict else "failed"

    print(json.dumps(summary, indent=2, default=str))
    return 0 if summary["status"] == "ok" else 1


async def _run_and_close(args: argparse.Namespace) -> int:
    try:
        return await _main(args)
    finally:
        await close_db()


def cli(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="utg-ingest",
        description="Load Urban Tandoor JSON snapshots into MongoDB Atlas.",
    )
    parser.add_argument(
        "--only",
        action="append",
        choices=DOMAINS,
        default=None,
        help="Run only the specified domain(s). Repeatable: --only menu --only docs",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Abort on first domain failure (default: continue, mark partial)",
    )
    parser.add_argument(
        "--wipe",
        action="store_true",
        help="DANGER: remove all documents from the 20 collections before ingesting. "
        "Requires --yes to confirm.",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Confirm --wipe without interactive prompt.",
    )
    parser.add_argument(
        "--json-dir",
        default=None,
        help="JSON snapshot directory (default: ./data/json).",
    )
    args = parser.parse_args(argv)
    return asyncio.run(_run_and_close(args))


if __name__ == "__main__":
    sys.exit(cli())
