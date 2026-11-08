from __future__ import annotations

from pydantic import BaseModel, Field


class ChunkResult(BaseModel):
    chunk_id: str
    document_id: str
    document_title: str | None = None
    section: str | None = None
    content: str
    token_count: int
    score: float = Field(description="Cosine similarity in [-1, 1]; higher = better")


class SemanticSearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    top_k: int = Field(default=8, ge=1, le=50)
    min_score: float = Field(default=0.0, ge=-1.0, le=1.0)


class SemanticSearchResponse(BaseModel):
    query: str
    top_k: int
    min_score: float
    count: int
    results: list[ChunkResult]


class SearchHealthResponse(BaseModel):
    chunks_total: int
    chunks_with_embedding: int
    distinct_documents: int
    embedding_dim: int
    vector_index_present: bool


class DocumentOut(BaseModel):
    document_id: str
    source_path: str
    source_type: str
    title: str | None
    checksum: str
    loaded_at: str
    chunk_count: int
