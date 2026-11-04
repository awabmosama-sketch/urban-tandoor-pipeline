"""
Document and embedding tables. Phase 4.

pgvector extension is required at the PostgreSQL level for the DocumentChunk.embedding
column to work at runtime. The extension is enabled by Alembic in Phase 5; this module
only declares the SQLAlchemy type.
"""
from datetime import datetime, timezone
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import Column, DateTime, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel

from app.config import get_settings

EMBEDDING_DIM = get_settings().embedding_dim


class SourceDocument(SQLModel, table=True):
    __tablename__ = "source_documents"

    document_id: str = Field(primary_key=True, max_length=128)
    source_path: str = Field(max_length=512)
    source_type: str = Field(max_length=32)     # "docx" | "xlsx_sheet" | "text"
    checksum: str = Field(max_length=64, index=True)   # sha256 hex
    title: str | None = Field(default=None, max_length=256)
    loaded_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_type=DateTime(timezone=True),
    )
    metadata_json: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSONB, nullable=False, server_default=text("'{}'::jsonb")),
    )


class DocumentChunk(SQLModel, table=True):
    __tablename__ = "document_chunks"

    chunk_id: str = Field(primary_key=True, max_length=160)
    document_id: str = Field(
        foreign_key="source_documents.document_id", max_length=128, index=True
    )
    ordinal: int = Field(default=0)
    content: str = Field(sa_column=Column(Text, nullable=False))
    token_count: int = Field(default=0)
    section: str | None = Field(default=None, max_length=256)
    embedding: list[float] | None = Field(
        default=None,
        sa_column=Column(Vector(EMBEDDING_DIM), nullable=True),
    )
    embedded_at: datetime | None = Field(
        default=None, sa_type=DateTime(timezone=True)
    )
    metadata_json: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSONB, nullable=False, server_default=text("'{}'::jsonb")),
    )
