"""
Semantic search service.

Uses pgvector's cosine-distance operator via SQLAlchemy's
`embedding.cosine_distance(vec)` which compiles to `embedding <=> :vec`.
Similarity = 1 - distance.

With FakeEmbedder, results are deterministic but not semantically meaningful —
structural correctness is what we test; relevance requires a real provider.
"""
from __future__ import annotations

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.ingestion.embedder import get_embedder
from app.models import DocumentChunk, SourceDocument
from app.schemas.search import ChunkResult


async def semantic_search(
    session: AsyncSession,
    *,
    query: str,
    top_k: int = 8,
    min_score: float = 0.0,
) -> list[ChunkResult]:
    """Returns top_k chunks with similarity >= min_score, ordered DESC."""
    embedder = get_embedder()
    vectors = await embedder.embed_batch([query])
    if not vectors:
        return []
    qvec = vectors[0]

    # pgvector distance operator. Similarity = 1 - cosine_distance.
    distance_expr = DocumentChunk.embedding.cosine_distance(qvec).label("distance")
    stmt = (
        select(DocumentChunk, distance_expr)
        .where(DocumentChunk.embedding.is_not(None))
        .order_by(distance_expr.asc())          # smallest distance = highest similarity
        .limit(top_k)
    )
    rows = (await session.execute(stmt)).all()
    if not rows:
        return []

    # Load document titles in one round-trip.
    doc_ids = list({row.DocumentChunk.document_id for row in rows})
    doc_rows = (await session.execute(
        select(SourceDocument.document_id, SourceDocument.title)
        .where(SourceDocument.document_id.in_(doc_ids))
    )).all()
    titles = {d: t for d, t in doc_rows}

    out: list[ChunkResult] = []
    for row in rows:
        chunk: DocumentChunk = row.DocumentChunk
        distance = float(row.distance)
        score = 1.0 - distance
        if score < min_score:
            continue
        out.append(ChunkResult(
            chunk_id=chunk.chunk_id,
            document_id=chunk.document_id,
            document_title=titles.get(chunk.document_id),
            section=chunk.section,
            content=chunk.content,
            token_count=chunk.token_count,
            score=round(score, 6),
        ))
    # Already DESC by similarity because we ORDER BY distance ASC and
    # filter preserves order.
    return out


async def search_health(session: AsyncSession) -> dict:
    """Aggregate stats about the search index."""
    total = (await session.execute(
        select(func.count()).select_from(DocumentChunk)
    )).scalar() or 0
    with_emb = (await session.execute(
        select(func.count()).select_from(DocumentChunk)
        .where(DocumentChunk.embedding.is_not(None))
    )).scalar() or 0
    distinct_docs = (await session.execute(
        select(func.count(func.distinct(DocumentChunk.document_id)))
    )).scalar() or 0

    # pgvector dim: query the column typmod
    emb_type = (await session.execute(text(
        "SELECT format_type(atttypid, atttypmod) FROM pg_attribute "
        "WHERE attrelid = 'document_chunks'::regclass AND attname = 'embedding'"
    ))).scalar() or ""
    dim = 0
    if "vector(" in (emb_type or ""):
        try:
            dim = int(str(emb_type).split("vector(")[1].rstrip(")"))
        except Exception:
            dim = 0

    hnsw = (await session.execute(text(
        "SELECT 1 FROM pg_indexes WHERE tablename='document_chunks' "
        "AND indexdef ILIKE '%USING hnsw%' LIMIT 1"
    ))).scalar()

    return {
        "chunks_total": int(total),
        "chunks_with_embedding": int(with_emb),
        "distinct_documents": int(distinct_docs),
        "embedding_dim": dim,
        "hnsw_index_present": bool(hnsw),
    }


async def list_documents(session: AsyncSession) -> list[dict]:
    """List source documents with their chunk counts."""
    stmt = (
        select(
            SourceDocument.document_id,
            SourceDocument.source_path,
            SourceDocument.source_type,
            SourceDocument.title,
            SourceDocument.checksum,
            SourceDocument.loaded_at,
            func.count(DocumentChunk.chunk_id).label("chunk_count"),
        )
        .outerjoin(DocumentChunk, DocumentChunk.document_id == SourceDocument.document_id)
        .group_by(
            SourceDocument.document_id, SourceDocument.source_path,
            SourceDocument.source_type, SourceDocument.title,
            SourceDocument.checksum, SourceDocument.loaded_at,
        )
        .order_by(SourceDocument.document_id)
    )
    rows = (await session.execute(stmt)).all()
    return [
        {
            "document_id": r.document_id,
            "source_path": r.source_path,
            "source_type": r.source_type,
            "title": r.title,
            "checksum": r.checksum,
            "loaded_at": r.loaded_at.isoformat() if r.loaded_at else "",
            "chunk_count": int(r.chunk_count),
        }
        for r in rows
    ]
