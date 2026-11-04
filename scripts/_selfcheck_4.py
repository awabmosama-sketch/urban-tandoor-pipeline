"""
Self-check for Phase 4. Run: python -m uv run python scripts/_selfcheck_4.py
Exits 0 on success, 1 on failure.

Phase 4 adds SourceDocument + DocumentChunk + a pgvector Vector(dim) column.
The two decisive checks:
  - vector dim in the model matches Settings().embedding_dim
  - FULL 20-TABLE DDL COMPILE under postgresql dialect (including VECTOR(1536))

SQLModel 0.0.48 quirks handled:
  - __table__.primary_key.columns for PKs
  - isinstance(f.foreign_key, str) for FKs
"""
import sys
from decimal import Decimal  # noqa: F401  (kept for regression parity with earlier phases)

from sqlalchemy import Table
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable
from sqlmodel import SQLModel

import app.models  # noqa: F401
from app.config import get_settings

results: list[tuple[str, str, object]] = []


def check(name: str, condition: bool, got: object = None) -> None:
    status = "PASS" if condition else "FAIL"
    results.append((name, status, got))
    suffix = "" if got is None else f"  (got: {got})"
    print(f"{status}  {name}{suffix}")


def get_fk(cls, field: str) -> str | None:
    fk = cls.model_fields[field].foreign_key
    return fk if isinstance(fk, str) else None


def pk_columns(cls) -> list[str]:
    return [c.name for c in cls.__table__.primary_key.columns]


# --- Regression: Phase 2/3 classes still importable and unchanged ---
from app.models.menu import (  # noqa: E402
    Addon, AllergenGuide, Branch, BranchMenu, BranchStock, Category, Deal,
    DealItem, Ingredient, InventoryLink, ItemAddon, ItemAlias, MenuItem,
    Recipe, ServiceRule, StockMovement, Supplier, Variant,
)
from app.models.documents import (  # noqa: E402
    EMBEDDING_DIM, DocumentChunk, SourceDocument,
)

check("all prior + new classes import ok", True)

for name, cls, exp in [
    ("Category", Category, 5), ("AllergenGuide", AllergenGuide, 4),
    ("ServiceRule", ServiceRule, 6), ("Deal", Deal, 12),
    ("MenuItem", MenuItem, 19), ("Variant", Variant, 8),
    ("ItemAlias", ItemAlias, 5), ("BranchMenu", BranchMenu, 10),
    ("InventoryLink", InventoryLink, 6), ("Addon", Addon, 9),
    ("ItemAddon", ItemAddon, 5), ("DealItem", DealItem, 5),
    ("Supplier", Supplier, 5), ("Branch", Branch, 7), ("Ingredient", Ingredient, 9),
    ("BranchStock", BranchStock, 20), ("Recipe", Recipe, 6),
    ("StockMovement", StockMovement, 10),
]:
    got = len(cls.model_fields)
    check(f"{name} field_count unchanged == {exp}", got == exp, got)

# --- New class field counts ---
for name, cls, exp in [
    ("SourceDocument", SourceDocument, 7),
    ("DocumentChunk", DocumentChunk, 9),
]:
    got = len(cls.model_fields)
    check(f"{name} field_count == {exp}", got == exp, got)

# --- Metadata: 20 tables total ---
expected_tables = sorted([
    "addons", "allergen_guide", "branch_menu", "branch_stock", "branches",
    "categories", "deal_items", "deals", "document_chunks", "ingredients",
    "inventory_links", "item_addons", "item_aliases", "menu_items", "recipes",
    "service_rules", "source_documents", "stock_movements", "suppliers", "variants",
])
got_tables = sorted(SQLModel.metadata.tables.keys())
check("metadata has 20 tables", got_tables == expected_tables, got_tables)

# ============================================================
# SourceDocument structural checks
# ============================================================
print()
print("--- SourceDocument ---")
check(
    "SourceDocument PK == [document_id]",
    pk_columns(SourceDocument) == ["document_id"],
    pk_columns(SourceDocument),
)
check(
    "SourceDocument.checksum is indexed",
    SourceDocument.__table__.c.checksum.index,
    SourceDocument.__table__.c.checksum.index,
)
check(
    "SourceDocument.metadata_json uses JSONB",
    "JSONB" in str(SourceDocument.__table__.c.metadata_json.type),
    str(SourceDocument.__table__.c.metadata_json.type),
)
check(
    "SourceDocument.loaded_at is timestamptz",
    getattr(SourceDocument.__table__.c.loaded_at.type, "timezone", False) is True,
    str(SourceDocument.__table__.c.loaded_at.type),
)

# ============================================================
# DocumentChunk structural checks
# ============================================================
print()
print("--- DocumentChunk ---")
check(
    "DocumentChunk PK == [chunk_id]",
    pk_columns(DocumentChunk) == ["chunk_id"],
    pk_columns(DocumentChunk),
)
check(
    "DocumentChunk.document_id -> source_documents.document_id",
    get_fk(DocumentChunk, "document_id") == "source_documents.document_id",
    get_fk(DocumentChunk, "document_id"),
)

# --- CRITICAL: embedding column is pgvector VECTOR(dim) ---
emb_type = DocumentChunk.__table__.c.embedding.type
check(
    "DocumentChunk.embedding type is pgvector VECTOR",
    type(emb_type).__name__ in {"Vector", "VECTOR"},
    type(emb_type).__name__,
)
check(
    f"DocumentChunk.embedding dim == {EMBEDDING_DIM}",
    getattr(emb_type, "dim", None) == EMBEDDING_DIM,
    getattr(emb_type, "dim", None),
)
check(
    "DocumentChunk.embedding matches Settings().embedding_dim",
    EMBEDDING_DIM == get_settings().embedding_dim,
    f"model={EMBEDDING_DIM} settings={get_settings().embedding_dim}",
)
check(
    "DocumentChunk.embedding is nullable",
    DocumentChunk.__table__.c.embedding.nullable is True,
    DocumentChunk.__table__.c.embedding.nullable,
)

check(
    "DocumentChunk.content uses TEXT",
    "TEXT" in str(DocumentChunk.__table__.c.content.type).upper(),
    str(DocumentChunk.__table__.c.content.type),
)
check(
    "DocumentChunk.metadata_json uses JSONB",
    "JSONB" in str(DocumentChunk.__table__.c.metadata_json.type),
    str(DocumentChunk.__table__.c.metadata_json.type),
)

# --- No relationships on new tables ---
print()
print("--- relationships ---")
for name, cls in [("SourceDocument", SourceDocument), ("DocumentChunk", DocumentChunk)]:
    rels = getattr(cls, "__sqlmodel_relationships__", {})
    check(f"{name} has no relationships", len(rels) == 0, len(rels))

# ============================================================
# FULL 20-TABLE DDL COMPILE
# ============================================================
print()
print("--- FULL 20-TABLE DDL COMPILE ---")
ddl_failures: list[str] = []
for table in SQLModel.metadata.sorted_tables:
    try:
        CreateTable(table).compile(dialect=postgresql.dialect())
    except Exception as exc:  # noqa: BLE001
        ddl_failures.append(f"{table.name}: {type(exc).__name__}: {str(exc)[:60]}")
check(
    "FULL DDL COMPILE — all 20 tables",
    len(ddl_failures) == 0,
    f"{len(ddl_failures)} failed: {ddl_failures}" if ddl_failures else "20/20 compiled",
)

# --- DocumentChunk DDL contains VECTOR(N) ---
dc_ddl = str(CreateTable(DocumentChunk.__table__).compile(dialect=postgresql.dialect()))
check(
    f"DocumentChunk DDL contains VECTOR({EMBEDDING_DIM})",
    f"VECTOR({EMBEDDING_DIM})" in dc_ddl.upper(),
    None,
)
check(
    "DocumentChunk DDL contains JSONB",
    "JSONB" in dc_ddl.upper(),
    None,
)

# ============================================================
# FINAL FK GRAPH CLOSURE — every FK across all 20 tables resolves.
# ============================================================
print()
print("--- FINAL FK GRAPH CLOSURE ---")
unresolved: list[str] = []
for table in SQLModel.metadata.sorted_tables:
    for fk in table.foreign_keys:
        target = fk.column.table.name
        if target not in SQLModel.metadata.tables:
            unresolved.append(f"{table.name}.{fk.parent.name} -> {target}")
check(
    "PHASE 4 CLOSURE — all 20 tables' FKs resolve",
    len(unresolved) == 0,
    f"{len(unresolved)} unresolved: {unresolved[:3]}" if unresolved else "0 unresolved",
)

# --- Summary ---
print()
print("=" * 60)
failed = [r for r in results if r[1] == "FAIL"]
print(f"PHASE 4 SELF-CHECK  —  {len(results) - len(failed)}/{len(results)} passed")
print("=" * 60)
if failed:
    print("FAILED CHECKS:")
    for name, _, got in failed:
        print(f"  - {name}  (got: {got})")
    print()
    print("RESULT: NEEDS FIX")
    sys.exit(1)
else:
    print(f"SCHEMA CLOSED: 20 tables, VECTOR({EMBEDDING_DIM}) column, all FKs resolve.")
    print("RESULT: READY FOR PHASE 5 (Alembic)")
    sys.exit(0)
