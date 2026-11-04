"""
Generic upsert helper. Inserts rows or updates on PK conflict.
Do not use pandas.DataFrame.to_sql — it has no upsert semantics.
"""
from __future__ import annotations

from typing import Any, Sequence
from sqlalchemy import Table
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import SQLModel


async def upsert_rows(
    session: AsyncSession,
    model: type[SQLModel],
    rows: Sequence[dict[str, Any]],
    pk_columns: Sequence[str],
) -> int:
    """Insert rows, updating on PK conflict. Returns rows processed.
    Rows must already have model-attribute names (not workbook headers).
    Every row must have every pk_column present and non-None.
    """
    if not rows:
        return 0
    table: Table = model.__table__
    stmt = pg_insert(table).values(list(rows))
    update_cols = {
        c.name: stmt.excluded[c.name]
        for c in table.columns
        if c.name not in pk_columns
    }
    stmt = stmt.on_conflict_do_update(
        index_elements=list(pk_columns),
        set_=update_cols,
    )
    await session.execute(stmt)
    return len(rows)
