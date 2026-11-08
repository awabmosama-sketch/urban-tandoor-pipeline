"""
Semantic search service (MongoDB).

For the demo dataset (128 chunks) cosine similarity is calculated in Python
with NumPy. This works on the MongoDB Atlas free tier without requiring an
Atlas Vector Search index. Scores are the same cosine similarity values the
previous relational vector query produced (``1 - cosine_distance``).

If the dataset grows, replace ``_rank_chunks`` with an Atlas ``$vectorSearch``
aggregation stage; the rest of the response contract stays unchanged.
"""
from __future__ import annotations

from datetime import datetime

import numpy as np
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.config import get_settings
from app.ingestion.embedder import get_embedder
from app.schemas.search import ChunkResult


def _normalise(vector: np.ndarray) -> np.ndarray:
    norm = float(np.linalg.norm(vector))
    return vector if norm == 0 else vector / norm


def _rank_chunks(
    chunks: list[dict],
    query_vector: list[float],
    *,
    top_k: int,
    min_score: float,
) -> list[tuple[dict, float]]:
    if not chunks:
        return []

    query = _normalise(np.asarray(query_vector, dtype=np.float64))
    matrix_rows: list[np.ndarray] = []
    valid_chunks: list[dict] = []
    for chunk in chunks:
        embedding = chunk.get("embedding")
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
        key=lambda pair: (-pair[1], pair[0].get("chunk_id", "")),
    )
    return [
        (chunk, score)
        for chunk, score in ranked
        if score >= min_score
    ][:top_k]


async def semantic_search(
    db: AsyncIOMotorDatabase,
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

    chunks = await db.document_chunks.find(
        {},
        {
            "chunk_id": 1,
            "document_id": 1,
            "section": 1,
            "content": 1,
            "token_count": 1,
            "embedding": 1,
        },
    ).to_list(length=None)

    ranked = _rank_chunks(
        chunks,
        query_vector,
        top_k=top_k,
        min_score=min_score,
    )
    if not ranked:
        return []

    document_ids = sorted({chunk["document_id"] for chunk, _ in ranked})
    document_docs = await db.source_documents.find(
        {"document_id": {"$in": document_ids}},
        {"document_id": 1, "title": 1},
    ).to_list(length=None)
    titles = {doc["document_id"]: doc.get("title") for doc in document_docs}

    return [
        ChunkResult(
            chunk_id=chunk["chunk_id"],
            document_id=chunk["document_id"],
            document_title=titles.get(chunk["document_id"]),
            section=chunk.get("section"),
            content=chunk["content"],
            token_count=int(chunk.get("token_count") or 0),
            score=round(float(score), 6),
        )
        for chunk, score in ranked
    ]


async def search_health(db: AsyncIOMotorDatabase) -> dict:
    """Aggregate stats about the search index."""
    chunks = await db.document_chunks.find(
        {},
        {"document_id": 1, "embedding": 1},
    ).to_list(length=None)

    total = len(chunks)
    with_embedding = [chunk for chunk in chunks if chunk.get("embedding")]
    distinct_documents = len({chunk.get("document_id") for chunk in chunks})

    embedding_dim = get_settings().embedding_dim
    if with_embedding:
        embedding_dim = len(with_embedding[0]["embedding"])

    return {
        "chunks_total": int(total),
        "chunks_with_embedding": len(with_embedding),
        "distinct_documents": int(distinct_documents),
        "embedding_dim": int(embedding_dim),
        # Cosine ranking currently happens in the application process.
        "vector_index_present": False,
    }


def _isoformat(value) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value or "")


async def list_documents(db: AsyncIOMotorDatabase) -> list[dict]:
    """List source documents with their chunk counts."""
    documents = await db.source_documents.find({}).sort("document_id", 1).to_list(length=None)
    output: list[dict] = []
    for document in documents:
        chunk_count = await db.document_chunks.count_documents(
            {"document_id": document["document_id"]}
        )
        output.append(
            {
                "document_id": document["document_id"],
                "source_path": document.get("source_path", ""),
                "source_type": document.get("source_type", ""),
                "title": document.get("title"),
                "checksum": document.get("checksum", ""),
                "loaded_at": _isoformat(document.get("loaded_at")),
                "chunk_count": int(chunk_count),
            }
        )
    return output
