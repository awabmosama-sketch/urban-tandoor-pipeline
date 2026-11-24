"""Read and write the canonical JSON snapshot files.

JSON is the ingestion boundary:

    Excel/DOCX -> data/json/<collection>.json -> MongoDB Atlas

The files contain plain JSON arrays. Decimals become numbers and dates become
ISO-8601 strings; the importer turns those strings back into BSON dates.
"""

from __future__ import annotations

import json
import math
import os
import tempfile
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from app.config import get_settings


def json_directory() -> Path:
    return Path(get_settings().json_dir)


def collection_path(name: str, directory: Path | None = None) -> Path:
    return (directory or json_directory()) / f"{name}.json"


def _json_default(value):
    if isinstance(value, Decimal):
        result = float(value)
        if not math.isfinite(result):
            raise ValueError(f"Non-finite decimal cannot be written to JSON: {value}")
        return result
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def write_collection(
    name: str,
    documents: list[dict],
    directory: Path | None = None,
) -> Path:
    """Write one collection as a pretty-printed JSON array."""
    target_dir = directory or json_directory()
    target_dir.mkdir(parents=True, exist_ok=True)
    path = collection_path(name, target_dir)
    payload = (
        json.dumps(
            documents,
            indent=2,
            ensure_ascii=False,
            default=_json_default,
        )
        + "\n"
    )

    # Write to a sibling file first so readers never observe a half-written
    # snapshot if the process dies mid-export. os.replace is atomic on both
    # POSIX and Windows.
    handle = tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=target_dir,
        prefix=f".{name}.",
        suffix=".tmp",
        delete=False,
    )
    temp_path = Path(handle.name)
    try:
        with handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
    finally:
        if temp_path.exists():
            temp_path.unlink()
    return path


def read_collection(
    name: str,
    directory: Path | None = None,
) -> list[dict]:
    """Read one collection JSON file."""
    path = collection_path(name, directory)
    if not path.exists():
        raise FileNotFoundError(
            f"JSON snapshot missing: {path}. Run `uv run utg-export` first."
        )
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError(f"{path} must contain a JSON array, got {type(data).__name__}")
    return data


def has_collection(name: str, directory: Path | None = None) -> bool:
    return collection_path(name, directory).exists()
