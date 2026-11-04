"""
Self-check for Phase 3a. Run: python -m uv run python scripts/_selfcheck_3a.py
Exits 0 on success, 1 on failure.

Phase 3a is the milestone where the FK graph closes. The two decisive checks
are:
  - PHASE 3A CLOSURE: every FK in metadata resolves to a table in metadata.
  - FULL DDL COMPILE: every table's DDL compiles under postgresql dialect.
If both pass, the 15-table schema is closed.
"""
import sys
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


from app.models.menu import (  # noqa: E402
    Addon, AllergenGuide, Branch, BranchMenu, Category, Deal, DealItem,
    Ingredient, InventoryLink, ItemAddon, ItemAlias, MenuItem, ServiceRule,
    Supplier, Variant,
)

check("all prior + new classes import ok", True)

# --- Regression: Phase 2 field counts unchanged ---
for name, cls, exp in [
    ("Category", Category, 5),
    ("AllergenGuide", AllergenGuide, 4),
    ("ServiceRule", ServiceRule, 6),
    ("Deal", Deal, 12),
    ("MenuItem", MenuItem, 19),
    ("Variant", Variant, 8),
    ("ItemAlias", ItemAlias, 5),
    ("BranchMenu", BranchMenu, 10),
    ("InventoryLink", InventoryLink, 6),
    ("Addon", Addon, 9),
    ("ItemAddon", ItemAddon, 5),
    ("DealItem", DealItem, 5),
]:
    got = len(cls.model_fields)
    check(f"{name} field_count unchanged == {exp}", got == exp, got)

# --- New class field counts ---
for name, cls, exp in [
    ("Supplier", Supplier, 5),
    ("Branch", Branch, 7),
    ("Ingredient", Ingredient, 9),
]:
    got = len(cls.model_fields)
    check(f"{name} field_count == {exp}", got == exp, got)

# --- Metadata: 15 tables total ---
expected_tables = sorted([
    "addons", "allergen_guide", "branch_menu", "branches", "categories",
    "deal_items", "deals", "ingredients", "inventory_links", "item_addons",
    "item_aliases", "menu_items", "service_rules", "suppliers", "variants",
])
got_tables = sorted(SQLModel.metadata.tables.keys())
check("metadata has 15 tables", got_tables == expected_tables, got_tables)

# --- Ingredient.supplier_id -> suppliers.supplier_id ---
ing_supplier_fk = Ingredient.model_fields["supplier_id"].foreign_key
check(
    "Ingredient.supplier_id -> suppliers.supplier_id",
    ing_supplier_fk == "suppliers.supplier_id",
    ing_supplier_fk,
)

# --- Ingredient.unit_cost_pkr is Decimal ---
check(
    "Ingredient.unit_cost_pkr annotation == Decimal",
    Ingredient.model_fields["unit_cost_pkr"].annotation == Decimal,
    Ingredient.model_fields["unit_cost_pkr"].annotation,
)

# --- Branch / Supplier have no FKs ---
for name, cls in [("Branch", Branch), ("Supplier", Supplier)]:
    fks = [f for f in cls.model_fields.values() if isinstance(f.foreign_key, str)]
    check(f"{name} has no foreign keys", len(fks) == 0, len(fks))

# --- Single-column primary keys (via __table__, not model_fields) ---
for name, cls, expected_pk in [
    ("Supplier", Supplier, "supplier_id"),
    ("Branch", Branch, "branch_id"),
    ("Ingredient", Ingredient, "ingredient_id"),
]:
    pk_cols = [c.name for c in cls.__table__.primary_key.columns]
    check(
        f"{name} PK == [{expected_pk}]",
        pk_cols == [expected_pk],
        pk_cols,
    )

# --- No relationships on new tables ---
for name, cls in [("Supplier", Supplier), ("Branch", Branch), ("Ingredient", Ingredient)]:
    rels = getattr(cls, "__sqlmodel_relationships__", {})
    check(f"{name} has no relationships", len(rels) == 0, len(rels))

# ============================================================
# PHASE 3A CLOSURE CHECK — every FK resolves to a table in metadata.
# This is the decisive test that Phase 2's forward references now close.
# ============================================================
print()
print("--- FK graph closure ---")
unresolved: list[str] = []
for table in SQLModel.metadata.sorted_tables:
    for fk in table.foreign_keys:
        target = fk.column.table.name
        if target not in SQLModel.metadata.tables:
            unresolved.append(f"{table.name}.{fk.parent.name} -> {target}")
check(
    "PHASE 3A CLOSURE — all FKs resolve",
    len(unresolved) == 0,
    f"{len(unresolved)} unresolved: {unresolved[:3]}" if unresolved else "0 unresolved",
)

# --- Full DDL compile of all 15 tables under postgresql dialect ---
print()
print("--- full DDL compile (all 15 tables) ---")
ddl_failures: list[str] = []
for table in SQLModel.metadata.sorted_tables:
    try:
        CreateTable(table).compile(dialect=postgresql.dialect())
    except Exception as exc:  # noqa: BLE001
        ddl_failures.append(f"{table.name}: {type(exc).__name__}")
check(
    "FULL DDL COMPILE — all 15 tables",
    len(ddl_failures) == 0,
    f"{len(ddl_failures)} failed: {ddl_failures}" if ddl_failures else "15/15 compiled",
)

# --- The 3 tables that were deferred in Phases 2c/2d now compile ---
for name, cls in [("BranchMenu", BranchMenu), ("InventoryLink", InventoryLink), ("Addon", Addon)]:
    try:
        CreateTable(cls.__table__).compile(dialect=postgresql.dialect())
        check(f"DEFERRED NOW RESOLVED: {name} DDL compiles", True)
    except Exception as exc:  # noqa: BLE001
        check(f"DEFERRED NOW RESOLVED: {name} DDL compiles", False, f"{type(exc).__name__}")

# --- Summary ---
print()
print("=" * 60)
failed = [r for r in results if r[1] == "FAIL"]
print(f"PHASE 3a SELF-CHECK  —  {len(results) - len(failed)}/{len(results)} passed")
print("=" * 60)
if failed:
    print("FAILED CHECKS:")
    for name, _, got in failed:
        print(f"  - {name}  (got: {got})")
    print()
    print("RESULT: NEEDS FIX")
    sys.exit(1)
else:
    print("RESULT: READY FOR PHASE 3b")
    sys.exit(0)
