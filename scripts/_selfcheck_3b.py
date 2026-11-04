"""
Self-check for Phase 3b. Run: python -m uv run python scripts/_selfcheck_3b.py
Exits 0 on success, 1 on failure.

Phase 3b closes the schema. Two decisive checks:
  - FULL 18-TABLE DDL COMPILE: every table's DDL compiles under postgresql.
  - FINAL FK GRAPH CLOSURE: every FK in metadata resolves.
Plus per-table structural checks on the three new tables.

SQLModel 0.0.48 quirks handled below:
  - model_fields[x].primary_key returns PydanticUndefined (truthy!) for non-PK
    fields. We use __table__.primary_key.columns for authoritative PK checks.
  - model_fields[x].foreign_key returns PydanticUndefined (truthy!) for non-FK
    fields. We use isinstance(f.foreign_key, str) for FK detection.
"""
import sys
from datetime import date
from decimal import Decimal

from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable
from sqlmodel import SQLModel

import app.models  # noqa: F401

results: list[tuple[str, str, object]] = []


def check(name: str, condition: bool, got: object = None) -> None:
    status = "PASS" if condition else "FAIL"
    results.append((name, status, got))
    suffix = "" if got is None else f"  (got: {got})"
    print(f"{status}  {name}{suffix}")


def get_fk(cls, field: str) -> str | None:
    """Return FK target string or None. Handles PydanticUndefined."""
    fk = cls.model_fields[field].foreign_key
    return fk if isinstance(fk, str) else None


def pk_columns(cls) -> list[str]:
    """Authoritative PK column names, in declaration order."""
    return [c.name for c in cls.__table__.primary_key.columns]


from app.models.menu import (  # noqa: E402
    Addon, AllergenGuide, Branch, BranchMenu, BranchStock, Category, Deal,
    DealItem, Ingredient, InventoryLink, ItemAddon, ItemAlias, MenuItem,
    Recipe, ServiceRule, StockMovement, Supplier, Variant,
)

check("all prior + new classes import ok", True)

# --- Regression: earlier phases untouched ---
for name, cls, exp in [
    ("Category", Category, 5), ("AllergenGuide", AllergenGuide, 4),
    ("ServiceRule", ServiceRule, 6), ("Deal", Deal, 12),
    ("MenuItem", MenuItem, 19), ("Variant", Variant, 8),
    ("ItemAlias", ItemAlias, 5), ("BranchMenu", BranchMenu, 10),
    ("InventoryLink", InventoryLink, 6), ("Addon", Addon, 9),
    ("ItemAddon", ItemAddon, 5), ("DealItem", DealItem, 5),
    ("Supplier", Supplier, 5), ("Branch", Branch, 7), ("Ingredient", Ingredient, 9),
]:
    got = len(cls.model_fields)
    check(f"{name} field_count unchanged == {exp}", got == exp, got)

# --- New class field counts ---
for name, cls, exp in [
    ("BranchStock", BranchStock, 20),
    ("Recipe", Recipe, 6),
    ("StockMovement", StockMovement, 10),
]:
    got = len(cls.model_fields)
    check(f"{name} field_count == {exp}", got == exp, got)

# --- Metadata: 18 tables total ---
expected_tables = sorted([
    "addons", "allergen_guide", "branch_menu", "branch_stock", "branches",
    "categories", "deal_items", "deals", "ingredients", "inventory_links",
    "item_addons", "item_aliases", "menu_items", "recipes", "service_rules",
    "stock_movements", "suppliers", "variants",
])
got_tables = sorted(SQLModel.metadata.tables.keys())
check("metadata has 18 tables", got_tables == expected_tables, got_tables)

# ============================================================
# BranchStock structural checks
# ============================================================
print()
print("--- BranchStock ---")

check(
    "BranchStock composite PK == [branch_id, ingredient_id]",
    pk_columns(BranchStock) == ["branch_id", "ingredient_id"],
    pk_columns(BranchStock),
)
check(
    "BranchStock.branch_id -> branches.branch_id",
    get_fk(BranchStock, "branch_id") == "branches.branch_id",
    get_fk(BranchStock, "branch_id"),
)
check(
    "BranchStock.ingredient_id -> ingredients.ingredient_id",
    get_fk(BranchStock, "ingredient_id") == "ingredients.ingredient_id",
    get_fk(BranchStock, "ingredient_id"),
)

# --- BranchStock stores BOTH raw inputs AND computed values ---
raw_inputs = {"opening", "received", "consumed", "wastage", "adjustment", "reserved"}
computed = {"on_hand", "available", "suggested_buy", "stock_status", "stock_value_pkr"}
bs_fields = set(BranchStock.model_fields.keys())
check(
    "BranchStock stores all raw inputs (opening..reserved)",
    raw_inputs.issubset(bs_fields),
    sorted(raw_inputs - bs_fields) or "all present",
)
check(
    "BranchStock stores all computed values (on_hand..stock_value_pkr)",
    computed.issubset(bs_fields),
    sorted(computed - bs_fields) or "all present",
)
check("BranchStock has snapshot_at", "snapshot_at" in bs_fields)

# --- Computed fields are nullable (ingestion populates them) ---
for fname in ["on_hand", "available", "suggested_buy", "stock_status", "stock_value_pkr"]:
    f = BranchStock.model_fields[fname]
    nullable = f.default is None
    check(f"BranchStock.{fname} is nullable", nullable, f"default={f.default!r}")

# --- Raw inputs are non-nullable (default 0.0) ---
for fname in ["opening", "received", "consumed", "wastage", "adjustment", "reserved"]:
    f = BranchStock.model_fields[fname]
    check(
        f"BranchStock.{fname} default == 0.0",
        f.default == 0.0,
        f"default={f.default!r}",
    )

# --- Decimal types ---
check(
    "BranchStock.unit_cost_pkr is Decimal",
    BranchStock.model_fields["unit_cost_pkr"].annotation == Decimal,
    BranchStock.model_fields["unit_cost_pkr"].annotation,
)
check(
    "BranchStock.stock_value_pkr is Decimal | None",
    str(BranchStock.model_fields["stock_value_pkr"].annotation) in
    ("Decimal | None", "decimal.Decimal | None", "typing.Optional[decimal.Decimal]"),
    BranchStock.model_fields["stock_value_pkr"].annotation,
)

# ============================================================
# Recipe structural checks
# ============================================================
print()
print("--- Recipe ---")

check(
    "Recipe composite PK == [menu_id, ingredient_id]",
    pk_columns(Recipe) == ["menu_id", "ingredient_id"],
    pk_columns(Recipe),
)
check(
    "Recipe.menu_id -> menu_items.menu_id",
    get_fk(Recipe, "menu_id") == "menu_items.menu_id",
    get_fk(Recipe, "menu_id"),
)
check(
    "Recipe.ingredient_id -> ingredients.ingredient_id",
    get_fk(Recipe, "ingredient_id") == "ingredients.ingredient_id",
    get_fk(Recipe, "ingredient_id"),
)

# --- Recipe MUST NOT contain workbook-derived columns ---
r_fields = set(Recipe.model_fields.keys())
forbidden_substrings = ("available", "max_portions", "pechs", "gulshan")
violations = [
    name for name in r_fields
    if any(s in name.lower() for s in forbidden_substrings)
]
check(
    "Recipe drops workbook-derived columns (no available/max_portions/pechs/gulshan)",
    len(violations) == 0,
    violations or "0 violations",
)
check(
    "Recipe has qty_per_portion",
    "qty_per_portion" in r_fields,
    None,
)

# --- qty_per_portion is float (NOT Decimal — it's units not money) ---
check(
    "Recipe.qty_per_portion is float",
    Recipe.model_fields["qty_per_portion"].annotation is float,
    Recipe.model_fields["qty_per_portion"].annotation,
)

# ============================================================
# StockMovement structural checks
# ============================================================
print()
print("--- StockMovement ---")

check(
    "StockMovement PK == [movement_id]",
    pk_columns(StockMovement) == ["movement_id"],
    pk_columns(StockMovement),
)
check(
    "StockMovement.branch_id -> branches.branch_id",
    get_fk(StockMovement, "branch_id") == "branches.branch_id",
    get_fk(StockMovement, "branch_id"),
)
check(
    "StockMovement.ingredient_id -> ingredients.ingredient_id",
    get_fk(StockMovement, "ingredient_id") == "ingredients.ingredient_id",
    get_fk(StockMovement, "ingredient_id"),
)
check(
    "StockMovement.movement_date is date",
    StockMovement.model_fields["movement_date"].annotation is date,
    StockMovement.model_fields["movement_date"].annotation,
)
check(
    "StockMovement.qty_signed is float",
    StockMovement.model_fields["qty_signed"].annotation is float,
    StockMovement.model_fields["qty_signed"].annotation,
)

# --- No relationships on new tables ---
print()
print("--- relationships ---")
for name, cls in [
    ("BranchStock", BranchStock), ("Recipe", Recipe), ("StockMovement", StockMovement),
]:
    rels = getattr(cls, "__sqlmodel_relationships__", {})
    check(f"{name} has no relationships", len(rels) == 0, len(rels))

# ============================================================
# FINAL FK GRAPH CLOSURE — every FK in metadata resolves.
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
    "PHASE 3B CLOSURE — all 18 tables' FKs resolve",
    len(unresolved) == 0,
    f"{len(unresolved)} unresolved: {unresolved[:3]}" if unresolved else "0 unresolved",
)

# ============================================================
# FULL 18-TABLE DDL COMPILE — final shippable gate.
# ============================================================
print()
print("--- FULL 18-TABLE DDL COMPILE ---")
ddl_failures: list[str] = []
for table in SQLModel.metadata.sorted_tables:
    try:
        CreateTable(table).compile(dialect=postgresql.dialect())
    except Exception as exc:  # noqa: BLE001
        ddl_failures.append(f"{table.name}: {type(exc).__name__}")
check(
    "FULL DDL COMPILE — all 18 tables",
    len(ddl_failures) == 0,
    f"{len(ddl_failures)} failed: {ddl_failures}" if ddl_failures else "18/18 compiled",
)

# --- DDL spot-checks on the three new tables ---
bs_ddl = str(CreateTable(BranchStock.__table__).compile(dialect=postgresql.dialect()))
check(
    "BranchStock DDL has NUMERIC(12, 2) for stock_value_pkr",
    "NUMERIC(12, 2)" in bs_ddl,
    None,
)
check(
    "BranchStock DDL has composite PRIMARY KEY",
    "PRIMARY KEY (branch_id, ingredient_id)" in bs_ddl,
    None,
)
sm_ddl = str(CreateTable(StockMovement.__table__).compile(dialect=postgresql.dialect()))
check("StockMovement DDL has DATE type", "DATE" in sm_ddl, None)

# --- Summary ---
print()
print("=" * 60)
failed = [r for r in results if r[1] == "FAIL"]
print(f"PHASE 3b SELF-CHECK  —  {len(results) - len(failed)}/{len(results)} passed")
print("=" * 60)
if failed:
    print("FAILED CHECKS:")
    for name, _, got in failed:
        print(f"  - {name}  (got: {got})")
    print()
    print("RESULT: NEEDS FIX")
    sys.exit(1)
else:
    print("SCHEMA CLOSED: 18 tables, all FKs resolve, all DDL compiles.")
    print("RESULT: READY FOR PHASE 4 (pgvector)")
    sys.exit(0)
