"""Load JSON snapshot files into MongoDB Atlas.

This is the only write path into the database. Excel/DOCX parsing writes JSON;
this module reads that JSON and performs idempotent upserts keyed on each
collection's natural key.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime

from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo import ReplaceOne

from app.collections import (
    ALL_COLLECTIONS,
    DOCS_COLLECTIONS,
    INVENTORY_COLLECTIONS,
    MENU_COLLECTIONS,
    NATURAL_KEYS,
)
from app.ingestion.embedder import get_embedder
from app.ingestion.json_store import read_collection

# JSON stores dates as ISO strings; restore them to BSON dates on import.
DATE_FIELDS: dict[str, tuple[str, ...]] = {
    "menu_items": ("updated_at",),
    "branch_stock": ("snapshot_at",),
    "stock_movements": ("movement_date",),
    "source_documents": ("loaded_at",),
    "document_chunks": ("embedded_at",),
}


def _parse_datetime(value):
    if value is None or isinstance(value, datetime):
        return value
    if not isinstance(value, str) or not value.strip():
        return value
    try:
        return datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return value


def _prepare_document(name: str, document: dict) -> dict:
    doc = dict(document)
    for field in DATE_FIELDS.get(name, ()):
        if field in doc:
            doc[field] = _parse_datetime(doc[field])
    return doc


def _upsert_ops(name: str, documents: Iterable[dict]) -> list[ReplaceOne]:
    keys = NATURAL_KEYS[name]
    operations: list[ReplaceOne] = []
    for raw in documents:
        doc = _prepare_document(name, raw)
        missing = [k for k in keys if doc.get(k) is None]
        if missing:
            raise ValueError(f"{name}: document missing natural key {missing}: {doc}")
        selector = {key: doc[key] for key in keys}
        operations.append(ReplaceOne(selector, doc, upsert=True))
    return operations


async def upsert_json_collection(
    db: AsyncIOMotorDatabase,
    name: str,
    documents: list[dict] | None = None,
) -> int:
    """Upsert one collection. Returns the number of JSON documents processed."""
    docs = documents if documents is not None else read_collection(name)
    if not docs:
        return 0
    operations = _upsert_ops(name, docs)
    try:
        await db[name].bulk_write(operations, ordered=False)
    except (AttributeError, NotImplementedError, TypeError):
        # Lightweight test doubles (mongomock) do not always implement a
        # compatible bulk_write. Point-by-point replace is equivalent because
        # every operation is an idempotent upsert on the natural key.
        for op in operations:
            await db[name].replace_one(op._filter, op._doc, upsert=True)
    return len(docs)


async def _prepare_document_chunks(db: AsyncIOMotorDatabase, chunks: list[dict]) -> list[dict]:
    """Embed chunks at import time, so the JSON stays small and readable."""
    if not chunks:
        return chunks
    embedder = get_embedder()
    vectors = await embedder.embed_batch([chunk["content"] for chunk in chunks])
    if len(vectors) != len(chunks):
        raise RuntimeError(
            f"embedder returned {len(vectors)} vectors for {len(chunks)} chunks"
        )
    now = datetime.now(UTC)
    prepared: list[dict] = []
    for chunk, vector in zip(chunks, vectors, strict=True):
        doc = dict(chunk)
        doc["embedding"] = list(vector)
        doc["embedded_at"] = now
        prepared.append(doc)
    return prepared


async def ingest_json_domain(
    db: AsyncIOMotorDatabase,
    domain: str,
) -> dict[str, int]:
    """Ingest one domain (menu | inventory | docs) from its JSON files."""
    if domain == "menu":
        names = MENU_COLLECTIONS
        counts: dict[str, int] = {}
        for name in names:
            counts[name] = await upsert_json_collection(db, name)
        return counts

    if domain == "inventory":
        names = INVENTORY_COLLECTIONS
        counts = {}
        for name in names:
            counts[name] = await upsert_json_collection(db, name)
        return counts

    if domain == "docs":
        source_documents = read_collection("source_documents")
        raw_chunks = read_collection("document_chunks")
        chunks = await _prepare_document_chunks(db, raw_chunks)
        counts = {
            "source_documents": await upsert_json_collection(
                db, "source_documents", source_documents
            ),
            "document_chunks": await upsert_json_collection(
                db, "document_chunks", chunks
            ),
        }
        return counts

    raise ValueError(f"unknown domain: {domain}")


async def ingest_all_json(db: AsyncIOMotorDatabase) -> dict[str, dict[str, int]]:
    """Ingest all three domains from JSON."""
    return {
        "menu": await ingest_json_domain(db, "menu"),
        "inventory": await ingest_json_domain(db, "inventory"),
        "docs": await ingest_json_domain(db, "docs"),
    }


async def wipe_all_collections(db: AsyncIOMotorDatabase) -> dict[str, int]:
    """Remove every document from the 20 business collections."""
    deleted: dict[str, int] = {}
    for name in ALL_COLLECTIONS:
        result = await db[name].delete_many({})
        deleted[name] = int(result.deleted_count)
    return deleted


__all__ = [
    "DOCS_COLLECTIONS",
    "ingest_all_json",
    "ingest_json_domain",
    "upsert_json_collection",
    "wipe_all_collections",
]
