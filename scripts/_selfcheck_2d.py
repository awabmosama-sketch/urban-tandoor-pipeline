"""
Self-check for Phase 2d. Run: python -m uv run python scripts/_selfcheck_2d.py
Exits 0 on success, 1 on failure.
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
    Addon, AllergenGuide, BranchMenu, Category, Deal, DealItem, InventoryLink,
    ItemAddon, ItemAlias, MenuItem, ServiceRule, Variant,
)

check("all prior + new classes import ok", True)

# --- Regression: earlier sub-phases untouched ---
check("Category fields == 5", len(Category.model_fields) == 5, len(Category.model_fields))
check("MenuItem fields == 19", len(MenuItem.model_fields) == 19, len(MenuItem.model_fields))
check("Variant fields == 8", len(Variant.model_fields) == 8, len(Variant.model_fields))
check("ItemAlias fields == 5", len(ItemAlias.model_fields) == 5, len(ItemAlias.model_fields))
check("BranchMenu fields == 10", len(BranchMenu.model_fields) == 10, len(BranchMenu.model_fields))
check("InventoryLink fields == 6", len(InventoryLink.model_fields) == 6, len(InventoryLink.model_fields))

# --- New class field counts ---
for name, cls, exp in [
    ("Addon", Addon, 9),
    ("ItemAddon", ItemAddon, 5),
    ("DealItem", DealItem, 5),
]:
    got = len(cls.model_fields)
    check(f"{name} field_count == {exp}", got == exp, got)

# --- Metadata: 12 tables total ---
expected_tables = sorted([
    "addons", "allergen_guide", "branch_menu", "categories", "deal_items",
    "deals", "inventory_links", "item_addons", "item_aliases", "menu_items",
    "service_rules", "variants",
])
got_tables = sorted(SQLModel.metadata.tables.keys())
check("metadata has 12 tables", got_tables == expected_tables, got_tables)

# --- ItemAddon FKs ---
check(
    "ItemAddon.menu_id -> menu_items.menu_id",
    ItemAddon.model_fields["menu_id"].foreign_key == "menu_items.menu_id",
    ItemAddon.model_fields["menu_id"].foreign_key,
)
check(
    "ItemAddon.addon_id -> addons.addon_id",
    ItemAddon.model_fields["addon_id"].foreign_key == "addons.addon_id",
    ItemAddon.model_fields["addon_id"].foreign_key,
)

# --- DealItem FKs ---
for field, target in [
    ("deal_id", "deals.deal_id"),
    ("menu_id", "menu_items.menu_id"),
    ("variant_id", "variants.variant_id"),
]:
    check(
        f"DealItem.{field} -> {target}",
        DealItem.model_fields[field].foreign_key == target,
        DealItem.model_fields[field].foreign_key,
    )

# --- DealItem composite PK (3 columns) ---
pks = sorted(n for n, f in DealItem.model_fields.items() if f.primary_key)
check(
    "DealItem composite PK == {deal_id, menu_id, variant_id}",
    set(pks) == {"deal_id", "menu_id", "variant_id"},
    pks,
)

# --- Addon.ingredient_id forward reference, nullable ---
ing_fk = Addon.model_fields["ingredient_id"].foreign_key
ing_nullable = Addon.model_fields["ingredient_id"].default is None
check(
    "Addon.ingredient_id -> ingredients.ingredient_id (forward, nullable)",
    ing_fk == "ingredients.ingredient_id" and ing_nullable,
    f"fk={ing_fk} nullable={ing_nullable}",
)

# --- Decimal money fields ---
check(
    "Addon.price_pkr annotation == Decimal",
    Addon.model_fields["price_pkr"].annotation == Decimal,
    Addon.model_fields["price_pkr"].annotation,
)

# --- No relationships on new tables ---
for name, cls in [("Addon", Addon), ("ItemAddon", ItemAddon), ("DealItem", DealItem)]:
    rels = getattr(cls, "__sqlmodel_relationships__", {})
    check(f"{name} has no relationships", len(rels) == 0, len(rels))

# --- DDL compile for tables whose FKs are all resolvable ---
# (Addon is skipped: ingredients table arrives in Phase 3)
for name, cls in [("ItemAddon", ItemAddon), ("DealItem", DealItem)]:
    try:
        CreateTable(cls.__table__).compile(dialect=postgresql.dialect())
        check(f"{name} DDL compiles", True)
    except Exception as exc:  # noqa: BLE001
        check(f"{name} DDL compiles", False, f"{type(exc).__name__}: {str(exc)[:100]}")

# --- DealItem DDL includes composite PRIMARY KEY ---
di_ddl = str(CreateTable(DealItem.__table__).compile(dialect=postgresql.dialect()))
has_composite_pk = "PRIMARY KEY" in di_ddl and all(
    col in di_ddl for col in ("deal_id", "menu_id", "variant_id")
)
check("DealItem DDL has composite PRIMARY KEY", has_composite_pk, None)

# --- Summary ---
print()
print("=" * 60)
failed = [r for r in results if r[1] == "FAIL"]
print(f"PHASE 2d SELF-CHECK  —  {len(results) - len(failed)}/{len(results)} passed")
print("=" * 60)
if failed:
    print("FAILED CHECKS:")
    for name, _, got in failed:
        print(f"  - {name}  (got: {got})")
    print()
    print("RESULT: NEEDS FIX")
    sys.exit(1)
else:
    print("RESULT: READY FOR PHASE 3a")
    sys.exit(0)
