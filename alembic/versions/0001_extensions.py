"""
0001: enable required PostgreSQL extensions.

pgvector  -> DocumentChunk.embedding (VECTOR(1536))
pg_trgm   -> fast ILIKE / fuzzy lookup on item_aliases.customer_phrase (Phase 11)

Revision ID: c7428c8d28af
Revises:
Create Date: 2026-11-04
"""
from alembic import op

revision = "c7428c8d28af"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")


def downgrade() -> None:
    # Leave extensions in place on downgrade — other schemas may use them.
    pass
