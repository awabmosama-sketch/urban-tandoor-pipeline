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
    """Aggregate stats about the search index without transferring embeddings."""
    pipeline = [
        {
            "$group": {
                "_id": None,
                "chunks_total": {"$sum": 1},
                "chunks_with_embedding": {
                    "$sum": {
                        "$cond": [
                            {
                                "$and": [
                                    {"$isArray": "$embedding"},
                                    {"$gt": [{"$size": "$embedding"}, 0]},
                                ]
                            },
                            1,
                            0,
                        ]
                    }
                },
                "document_ids": {"$addToSet": "$document_id"},
                "embedding_dim": {
                    "$max": {
                        "$cond": [
                            {"$isArray": "$embedding"},
                            {"$size": "$embedding"},
                            0,
                        ]
                    }
                },
            }
        }
    ]
    rows = await db.document_chunks.aggregate(pipeline).to_list(length=1)
    stats = rows[0] if rows else {}

    distinct_documents = {
        document_id
        for document_id in stats.get("document_ids", [])
        if document_id is not None
    }
    embedding_dim = int(stats.get("embedding_dim") or 0) or get_settings().embedding_dim

    return {
        "chunks_total": int(stats.get("chunks_total", 0)),
        "chunks_with_embedding": int(stats.get("chunks_with_embedding", 0)),
        "distinct_documents": len(distinct_documents),
        "embedding_dim": int(embedding_dim),
        # Cosine ranking currently happens in the application process.
        "vector_index_present": False,
    }


def _isoformat(value) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value or "")


async def list_documents(db: AsyncIOMotorDatabase) -> list[dict]:
    """List source documents with their chunk counts in two queries."""
    count_rows = await db.document_chunks.aggregate(
        [{"$group": {"_id": "$document_id", "count": {"$sum": 1}}}]
    ).to_list(length=None)
    counts = {
        row["_id"]: int(row["count"])
        for row in count_rows
        if row.get("_id") is not None
    }

    documents = await db.source_documents.find({}).sort("document_id", 1).to_list(length=None)
    return [
        {
            "document_id": document["document_id"],
            "source_path": document.get("source_path", ""),
            "source_type": document.get("source_type", ""),
            "title": document.get("title"),
            "checksum": document.get("checksum", ""),
            "loaded_at": _isoformat(document.get("loaded_at")),
            "chunk_count": counts.get(document["document_id"], 0),
        }
        for document in documents
    ]
