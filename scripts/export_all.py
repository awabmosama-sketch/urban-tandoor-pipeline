"""
Export Excel/DOCX sources to the canonical JSON snapshots.

Usage:
  python scripts/export_all.py [--only DOMAIN ...] [--json-dir PATH]

Domains: menu, inventory, docs
JSON is written to ``data/json/<collection>.json`` by default.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from app.config import get_settings
from app.ingestion.docs_pipeline import export_docs_json
from app.ingestion.excel_inventory import export_inventory_json
from app.ingestion.excel_menu import export_menu_json

DOMAINS = ("menu", "inventory", "docs")


def _run_domain(name: str, export_fn: Callable[[], dict]) -> dict:
    started = time.monotonic()
    print(f"[export] {name}: starting", file=sys.stderr)
    try:
        counts = export_fn()
        duration = time.monotonic() - started
        print(f"[export] {name}: ok ({duration:.2f}s)", file=sys.stderr)
        return {"status": "ok", "collections": counts, "duration_s": round(duration, 2)}
    except Exception as exc:  # noqa: BLE001
        duration = time.monotonic() - started
        print(f"[export] {name}: ERROR {type(exc).__name__}: {exc}", file=sys.stderr)
        return {
            "status": "error",
            "error": str(exc),
            "type": type(exc).__name__,
            "duration_s": round(duration, 2),
        }


def _main(args: argparse.Namespace) -> int:
    if args.json_dir:
        # `--json-dir` is applied through the environment so every exporter
        # sees the same destination.
        import os

        os.environ["JSON_DIR"] = args.json_dir
        get_settings.cache_clear()

    started = time.monotonic()
    domains = args.only or list(DOMAINS)
    export_fns = {
        "menu": export_menu_json,
        "inventory": export_inventory_json,
        "docs": export_docs_json,
    }

    summary: dict = {
        "status": "ok",
        "json_dir": str(Path(get_settings().json_dir).resolve()),
        "started_at": datetime.now(UTC).isoformat(),
        "domains_requested": domains,
        "domains": {},
        "errors": [],
    }

    for name in domains:
        result = _run_domain(name, export_fns[name])
        summary["domains"][name] = result
        if result["status"] == "error":
            summary["errors"].append(
                {"domain": name, **{k: result[k] for k in ("error", "type")}}
            )
            if args.strict:
                print(f"[export] strict mode: aborting after {name} failure", file=sys.stderr)
                break

    summary["duration_s"] = round(time.monotonic() - started, 2)
    summary["finished_at"] = datetime.now(UTC).isoformat()
    if summary["errors"]:
        summary["status"] = "partial" if not args.strict else "failed"

    print(json.dumps(summary, indent=2, default=str))
    return 0 if summary["status"] == "ok" else 1


def cli(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="utg-export",
        description="Export Urban Tandoor Excel/DOCX sources to JSON snapshots.",
    )
    parser.add_argument(
        "--only",
        action="append",
        choices=DOMAINS,
        default=None,
        help="Export only the specified domain(s). Repeatable.",
    )
    parser.add_argument(
        "--json-dir",
        default=None,
        help="Destination directory (default: ./data/json).",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Abort on first domain failure.",
    )
    args = parser.parse_args(argv)
    return _main(args)


if __name__ == "__main__":
    sys.exit(cli())
