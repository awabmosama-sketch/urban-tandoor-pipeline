"""Load canonical JSON snapshots into PostgreSQL / Neon.

This mirrors ``app.ingestion.json_ingest`` (MongoDB) but is backend-agnostic:
Excel/DOCX are always parsed first and written to ``data/json``; this module
only reads those JSON files and performs idempotent upserts on the primary key.
Embeddings are generated here, so the committed JSON stays small.
"""
from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Date, DateTime, Numeric, Table
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import SQLModel

from app.backends.postgres.models import COLLECTION_MODELS
from app.collections import (
    ALL_COLLECTIONS,
    DOCS_COLLECTIONS,
    INVENTORY_COLLECTIONS,
    MENU_COLLECTIONS,
)
from app.ingestion.embedder import get_embedder
from app.ingestion.json_store import read_collection

# Rows per INSERT batch. Keeps us below PostgreSQL's 65535 bind-parameter limit
# for wide tables (document chunks carry a 1536-float embedding).
_MAX_BIND_PARAMS = 30_000


def _parse_date(value: Any) -> date | None:
    if value is None or isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            return date.fromisoformat(text[:10])
        except ValueError:
            return None
    return None


def _parse_datetime(value: Any) -> datetime | None:
    if value is None or isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def _coerce_row(table: Table, row: dict[str, Any]) -> dict[str, Any]:
    """Convert JSON primitives to the Python types the columns expect."""
    output: dict[str, Any] = {}
    for column in table.columns:
        if column.name not in row:
            continue
        value = row[column.name]
        if value is None:
            output[column.name] = None
            continue
        column_type = column.type
        if isinstance(column_type, DateTime):
            output[column.name] = _parse_datetime(value)
        elif isinstance(column_type, Date):
            output[column.name] = _parse_date(value)
        elif isinstance(column_type, Numeric):
            output[column.name] = Decimal(str(value))
        elif isinstance(column_type, ARRAY):
            output[column.name] = [float(v) for v in value]
        elif isinstance(column_type, JSONB):
            output[column.name] = value
        else:
            output[column.name] = value
    return output


def _primary_keys(model: type[SQLModel]) -> list[str]:
    return [column.name for column in model.__table__.primary_key.columns]


def _batch_size(table: Table) -> int:
    width = max(len(table.columns), 1)
    return max(1, _MAX_BIND_PARAMS // width)


async def _upsert_rows(
    session: AsyncSession,
    model: type[SQLModel],
    rows: list[dict[str, Any]],
) -> int:
    if not rows:
        return 0
    table = model.__table__
    pk_columns = _primary_keys(model)
    for row in rows:
        missing = [key for key in pk_columns if row.get(key) is None]
        if missing:
            raise ValueError(f"{table.name}: row missing primary key {missing}: {row}")

    update_columns = [
        column.name for column in table.columns if column.name not in pk_columns
    ]
    size = _batch_size(table)
    for start in range(0, len(rows), size):
        batch = rows[start : start + size]
        statement = pg_insert(table).values(batch)
        statement = statement.on_conflict_do_update(
            index_elements=pk_columns,
            set_={name: statement.excluded[name] for name in update_columns},
        )
        await session.execute(statement)
    return len(rows)


async def upsert_json_collection(
    session: AsyncSession,
    name: str,
    documents: list[dict[str, Any]] | None = None,
) -> int:
    """Upsert one collection from JSON. Returns documents processed."""
    model = COLLECTION_MODELS[name]
    raw_rows = documents if documents is not None else read_collection(name)
    if not raw_rows:
        return 0
    rows = [_coerce_row(model.__table__, row) for row in raw_rows]
    return await _upsert_rows(session, model, rows)


async def _embed_chunks(chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not chunks:
        return chunks
    embedder = get_embedder()
    vectors = await embedder.embed_batch([chunk["content"] for chunk in chunks])
    if len(vectors) != len(chunks):
        raise RuntimeError(
            f"embedder returned {len(vectors)} vectors for {len(chunks)} chunks"
        )
    now = datetime.now(UTC)
    prepared: list[dict[str, Any]] = []
    for chunk, vector in zip(chunks, vectors, strict=True):
        row = dict(chunk)
        row["embedding"] = [float(v) for v in vector]
        row["embedded_at"] = now
        prepared.append(row)
    return prepared


async def ingest_json_domain(session: AsyncSession, domain: str) -> dict[str, int]:
    """Ingest one domain (menu | inventory | docs) from its JSON files."""
    if domain == "menu":
        names = MENU_COLLECTIONS
        counts: dict[str, int] = {}
        for name in names:
            counts[name] = await upsert_json_collection(session, name)
        return counts

    if domain == "inventory":
        names = INVENTORY_COLLECTIONS
        counts = {}
        for name in names:
            counts[name] = await upsert_json_collection(session, name)
        return counts

    if domain == "docs":
        source_documents = read_collection("source_documents")
        raw_chunks = read_collection("document_chunks")
        chunks = await _embed_chunks(raw_chunks)
        counts = {
            "source_documents": await upsert_json_collection(
                session, "source_documents", source_documents
            ),
            "document_chunks": await upsert_json_collection(
                session, "document_chunks", chunks
            ),
        }
        return counts

    raise ValueError(f"unknown domain: {domain}")


async def ingest_all_json(session: AsyncSession) -> dict[str, dict[str, int]]:
    """Ingest all three domains from JSON."""
    return {
        "menu": await ingest_json_domain(session, "menu"),
        "inventory": await ingest_json_domain(session, "inventory"),
        "docs": await ingest_json_domain(session, "docs"),
    }


async def ingest_domain_with_export(session: AsyncSession, domain: str) -> dict[str, Any]:
    """Re-export the source workbooks to JSON, then load that JSON."""
    if domain in ("menu", "all"):
        from app.ingestion.excel_menu import export_menu_json

        export_menu_json()
    if domain in ("inventory", "all"):
        from app.ingestion.excel_inventory import export_inventory_json

        export_inventory_json()
    if domain in ("docs", "all"):
        from app.ingestion.docs_pipeline import export_docs_json

        export_docs_json()

    if domain == "all":
        return await ingest_all_json(session)
    return await ingest_json_domain(session, domain)


async def wipe_all(session: AsyncSession) -> None:
    """Truncate all 20 business tables atomically."""
    from sqlalchemy import text

    tables = ", ".join(f'"{name}"' for name in ALL_COLLECTIONS)
    await session.execute(text(f"TRUNCATE TABLE {tables} RESTART IDENTITY CASCADE"))
    await session.commit()


__all__ = [
    "DOCS_COLLECTIONS",
    "ingest_all_json",
    "ingest_domain_with_export",
    "ingest_json_domain",
    "upsert_json_collection",
    "wipe_all",
]
