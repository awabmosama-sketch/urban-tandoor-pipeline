from __future__ import annotations
import hashlib
import uuid
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.ingestion.chunker import chunk_sections
from app.ingestion.docx_loader import load_docx_sections
from app.ingestion.embedder import get_embedder
from app.models import DocumentChunk, MenuItem, SourceDocument


def _sha256_of_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _sha256_of_text(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


async def _get_source_doc(session: AsyncSession, document_id: str):
    return (await session.execute(
        select(SourceDocument).where(SourceDocument.document_id == document_id)
    )).scalar_one_or_none()


async def _upsert_source_doc(
    session: AsyncSession, *, document_id: str, source_path: str,
    source_type: str, checksum: str, title: str,
) -> SourceDocument:
    now = datetime.now(timezone.utc)
    existing = await _get_source_doc(session, document_id)
    if existing is None:
        doc = SourceDocument(
            document_id=document_id, source_path=source_path,
            source_type=source_type, checksum=checksum, title=title,
            loaded_at=now, metadata_json={},
        )
        session.add(doc)
        await session.flush()
        return doc
    existing.source_path = source_path
    existing.source_type = source_type
    existing.checksum = checksum
    existing.title = title
    existing.loaded_at = now
    session.add(existing)
    await session.flush()
    return existing


async def _delete_chunks_for(session: AsyncSession, document_id: str) -> int:
    r = await session.execute(
        delete(DocumentChunk).where(DocumentChunk.document_id == document_id)
    )
    return r.rowcount or 0


async def _insert_chunks(
    session: AsyncSession, *, document_id: str, chunks: list[dict],
    embedder, extra_metadata: dict | None = None,
) -> int:
    if not chunks:
        return 0
    texts = [c["content"] for c in chunks]
    vectors = await embedder.embed_batch(texts)
    if len(vectors) != len(texts):
        raise RuntimeError(
            f"embedder returned {len(vectors)} vectors for {len(texts)} texts"
        )
    now = datetime.now(timezone.utc)
    for i, (chunk, vec) in enumerate(zip(chunks, vectors)):
        meta = {"section": chunk.get("section")}
        if extra_metadata:
            meta.update(extra_metadata)
        chunk_id = f"{document_id}:{i:04d}"
        session.add(DocumentChunk(
            chunk_id=chunk_id,
            document_id=document_id,
            ordinal=i,
            content=chunk["content"],
            token_count=int(chunk.get("token_count") or 0),
            section=chunk.get("section"),
            embedding=vec,
            embedded_at=now,
            metadata_json=meta,
        ))
    await session.flush()
    return len(chunks)


async def ingest_profile(session: AsyncSession, docx_path: Path) -> dict:
    settings = get_settings()
    document_id = "docx:urban_tandoor_profile"
    checksum = _sha256_of_file(docx_path)
    existing = await _get_source_doc(session, document_id)
    if existing and existing.checksum == checksum:
        n = (await session.execute(
            text("SELECT count(*) FROM document_chunks WHERE document_id = :d"),
            {"d": document_id},
        )).scalar()
        if n and n > 0:
            return {"status": "skipped", "document_id": document_id, "chunks": int(n)}

    await _upsert_source_doc(
        session, document_id=document_id, source_path=str(docx_path),
        source_type="docx", checksum=checksum,
        title="Urban Tandoor & Grill — Restaurant Profile",
    )
    await _delete_chunks_for(session, document_id)
    sections = load_docx_sections(docx_path)
    chunks = chunk_sections(
        sections,
        chunk_size=settings.chunk_size,
        overlap=settings.chunk_overlap,
    )
    embedder = get_embedder()
    inserted = await _insert_chunks(
        session, document_id=document_id, chunks=chunks, embedder=embedder,
    )
    return {"status": "ingested", "document_id": document_id, "chunks": inserted}


async def ingest_menu_narratives(session: AsyncSession) -> dict:
    """One synthetic document with 118 chunks — one per menu item. Checksum
    derived from menu item fields, so ANY item change triggers regeneration."""
    settings = get_settings()
    document_id = "menu:catalog_narratives"

    rows = (await session.execute(
        select(MenuItem).order_by(MenuItem.menu_id)
    )).scalars().all()
    if not rows:
        return {"status": "skipped_no_menu_items", "document_id": document_id, "chunks": 0}

    parts = []
    for r in rows:
        parts.append(
            f"{r.menu_id}|{r.item_name}|{r.category}|{r.dietary_hint or ''}|"
            f"{r.allergen_hint or ''}|{r.base_price_pkr}|{r.prep_time_min}"
        )
    checksum = _sha256_of_text("\n".join(parts))

    existing = await _get_source_doc(session, document_id)
    if existing and existing.checksum == checksum:
        n = (await session.execute(
            text("SELECT count(*) FROM document_chunks WHERE document_id = :d"),
            {"d": document_id},
        )).scalar()
        if n and n > 0:
            return {"status": "skipped", "document_id": document_id, "chunks": int(n)}

    await _upsert_source_doc(
        session, document_id=document_id,
        source_path="<synthetic:menu_items>",
        source_type="xlsx_sheet", checksum=checksum,
        title="Menu catalog narratives (one chunk per menu item)",
    )
    await _delete_chunks_for(session, document_id)

    chunks = []
    for r in rows:
        content = (
            f"{r.menu_id} {r.item_name}. "
            f"Category: {r.category}. "
            f"Description: {r.description or 'traditional preparation'}. "
            f"Dietary hint: {r.dietary_hint or 'not verified'}. "
            f"Allergen hint: {r.allergen_hint or 'not verified'}. "
            f"Base price PKR {r.base_price_pkr}. "
            f"Preparation time {r.prep_time_min} minutes. "
            f"Service window: {r.service_window}."
        )
        chunks.append({
            "section": r.category,
            "content": content,
            "token_count": len(content.split()),
        })

    embedder = get_embedder()
    inserted = await _insert_chunks(
        session, document_id=document_id, chunks=chunks, embedder=embedder,
    )
    return {"status": "ingested", "document_id": document_id, "chunks": inserted}


async def ingest_all_docs(session: AsyncSession) -> dict:
    settings = get_settings()
    docx_path = Path(settings.data_dir) / "Urban_Tandoor_Grill_Restaurant_Profile.docx"
    if not docx_path.exists():
        raise FileNotFoundError(
            f"DOCX missing at {docx_path}. Place Urban_Tandoor_Grill_Restaurant_Profile.docx "
            "in data/ before running Phase 8."
        )
    result: dict = {}
    result["profile"] = await ingest_profile(session, docx_path)
    result["menu_narratives"] = await ingest_menu_narratives(session)
    return result
