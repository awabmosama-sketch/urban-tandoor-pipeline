"""Read and write the canonical JSON snapshot files.

JSON is the ingestion boundary:

    Excel/DOCX -> data/json/<collection>.json -> MongoDB Atlas

The files contain plain JSON arrays. Decimals become numbers and dates become
ISO-8601 strings; the importer turns those strings back into BSON dates.
"""

from __future__ import annotations

import json
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
        return float(value)
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
    path.write_text(
        json.dumps(
            documents,
            indent=2,
            ensure_ascii=False,
            default=_json_default,
        )
        + "\n",
        encoding="utf-8",
    )
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
