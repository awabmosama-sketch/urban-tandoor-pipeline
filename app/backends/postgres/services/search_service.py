"""
Semantic search service (PostgreSQL / Neon).

Embeddings are stored as plain ``float[]`` arrays, so cosine similarity is
computed in Python with NumPy — the same strategy and score contract as the
MongoDB backend. This keeps the backend portable (no pgvector extension) and
works on the Neon free tier.
"""
from __future__ import annotations

from datetime import datetime

import numpy as np
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.backends.postgres.models import DocumentChunk, SourceDocument
from app.config import get_settings
from app.ingestion.embedder import get_embedder
from app.schemas.search import ChunkResult


def _normalise(vector: np.ndarray) -> np.ndarray:
    norm = float(np.linalg.norm(vector))
    return vector if norm == 0 else vector / norm


def _rank_chunks(
    chunks: list[DocumentChunk],
    query_vector: list[float],
    *,
    top_k: int,
    min_score: float,
) -> list[tuple[DocumentChunk, float]]:
    if not chunks:
        return []

    query = _normalise(np.asarray(query_vector, dtype=np.float64))
    matrix_rows: list[np.ndarray] = []
    valid_chunks: list[DocumentChunk] = []
    for chunk in chunks:
        embedding = chunk.embedding
        if not embedding:
            continue
        vector = np.asarray(embedding, dtype=np.float64)
        if vector.shape != query.shape:
            continue
        matrix_rows.append(_normalise(vector))
        valid_chunks.append(chunk)
    if not matrix_rows:
        return []

    matrix = np.vstack(matrix_rows)
    scores = matrix @ query
    ranked = sorted(
        zip(valid_chunks, scores.tolist(), strict=True),
        key=lambda pair: (-pair[1], pair[0].chunk_id),
    )
    return [
        (chunk, score)
        for chunk, score in ranked
        if score >= min_score
    ][:top_k]


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
    query_vector = vectors[0]

    stmt = select(DocumentChunk).where(DocumentChunk.embedding.is_not(None))
    chunks = list((await session.execute(stmt)).scalars().all())

    ranked = _rank_chunks(
        chunks,
        query_vector,
        top_k=top_k,
        min_score=min_score,
    )
    if not ranked:
        return []

    document_ids = sorted({chunk.document_id for chunk, _ in ranked})
    title_stmt = select(SourceDocument.document_id, SourceDocument.title).where(
        SourceDocument.document_id.in_(document_ids)
    )
    title_rows = (await session.execute(title_stmt)).all()
    titles = {document_id: title for document_id, title in title_rows}

    return [
        ChunkResult(
            chunk_id=chunk.chunk_id,
            document_id=chunk.document_id,
            document_title=titles.get(chunk.document_id),
            section=chunk.section,
            content=chunk.content,
            token_count=int(chunk.token_count or 0),
            score=round(float(score), 6),
        )
        for chunk, score in ranked
    ]


async def search_health(session: AsyncSession) -> dict:
    """Aggregate stats about the search index."""
    total = (
        await session.execute(select(func.count()).select_from(DocumentChunk))
    ).scalar() or 0
    with_embedding = (
        await session.execute(
            select(func.count())
            .select_from(DocumentChunk)
            .where(DocumentChunk.embedding.is_not(None))
        )
    ).scalar() or 0
    distinct_documents = (
        await session.execute(
            select(func.count(func.distinct(DocumentChunk.document_id)))
        )
    ).scalar() or 0

    embedding_dim = get_settings().embedding_dim
    sample = (
        await session.execute(
            select(DocumentChunk.embedding)
            .where(DocumentChunk.embedding.is_not(None))
            .limit(1)
        )
    ).scalar()
    if sample:
        embedding_dim = len(sample)

    return {
        "chunks_total": int(total),
        "chunks_with_embedding": int(with_embedding),
        "distinct_documents": int(distinct_documents),
        "embedding_dim": int(embedding_dim),
        # Cosine ranking happens in the application process.
        "vector_index_present": False,
    }


def _isoformat(value: datetime | None) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value or "")


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
        .outerjoin(
            DocumentChunk,
            DocumentChunk.document_id == SourceDocument.document_id,
        )
        .group_by(
            SourceDocument.document_id,
            SourceDocument.source_path,
            SourceDocument.source_type,
            SourceDocument.title,
            SourceDocument.checksum,
            SourceDocument.loaded_at,
        )
        .order_by(SourceDocument.document_id)
    )
    rows = (await session.execute(stmt)).all()
    return [
        {
            "document_id": row.document_id,
            "source_path": row.source_path,
            "source_type": row.source_type,
            "title": row.title,
            "checksum": row.checksum,
            "loaded_at": _isoformat(row.loaded_at),
            "chunk_count": int(row.chunk_count),
        }
        for row in rows
    ]
