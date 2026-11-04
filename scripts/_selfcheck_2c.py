"""
Self-check for Phase 2c. Run: python -m uv run python scripts/_selfcheck_2c.py
Exits 0 on success, 1 on failure.
"""
import sys
from decimal import Decimal

from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable
from sqlmodel import SQLModel

import app.models  # noqa: F401  (registers tables)

results: list[tuple[str, str, object]] = []


def check(name: str, condition: bool, got: object = None) -> None:
    status = "PASS" if condition else "FAIL"
    results.append((name, status, got))
    suffix = "" if got is None else f"  (got: {got})"
    print(f"{status}  {name}{suffix}")


# --- REGRESSION: Phase 2a + 2b still intact ---
from app.models.menu import (  # noqa: E402
    AllergenGuide,
    BranchMenu,
    Category,
    Deal,
    InventoryLink,
    ItemAlias,
    MenuItem,
    ServiceRule,
    Variant,
)

check("Phase 2a import ok", True)
check("Category fields == 5", len(Category.model_fields) == 5, len(Category.model_fields))
check("MenuItem fields == 19", len(MenuItem.model_fields) == 19, len(MenuItem.model_fields))

# --- CHECK 2: new class imports ---
check("Phase 2c import ok", True)

# --- CHECK 3: field counts ---
expected_counts = {
    "Variant": (Variant, 8),
    "ItemAlias": (ItemAlias, 5),
    "BranchMenu": (BranchMenu, 10),
    "InventoryLink": (InventoryLink, 6),
}
for name, (cls, exp) in expected_counts.items():
    got = len(cls.model_fields)
    check(f"{name} field_count == {exp}", got == exp, got)

# --- CHECK 4: metadata tables == 9 ---
expected_tables = sorted([
    "allergen_guide", "branch_menu", "categories", "deals", "inventory_links",
    "item_aliases", "menu_items", "service_rules", "variants",
])
got_tables = sorted(SQLModel.metadata.tables.keys())
check("metadata has 9 tables", got_tables == expected_tables, got_tables)

# --- CHECK 5: menu_id FK on all four new tables ---
for name, cls in [
    ("Variant", Variant), ("ItemAlias", ItemAlias),
    ("BranchMenu", BranchMenu), ("InventoryLink", InventoryLink),
]:
    fk = cls.model_fields["menu_id"].foreign_key
    check(f"{name}.menu_id -> menu_items.menu_id", fk == "menu_items.menu_id", fk)

# --- CHECK 6: branch_id forward-reference string on the two branch tables ---
for name, cls in [("BranchMenu", BranchMenu), ("InventoryLink", InventoryLink)]:
    fk = cls.model_fields["branch_id"].foreign_key
    check(f"{name}.branch_id -> branches.branch_id (forward)", fk == "branches.branch_id", fk)

# --- CHECK 7: Decimal on the two price fields ---
v_price = Variant.model_fields["price_pkr"].annotation
check("Variant.price_pkr annotation == Decimal", v_price == Decimal, v_price)
bm_price = BranchMenu.model_fields["price_pkr"].annotation
check("BranchMenu.price_pkr annotation == Decimal", bm_price == Decimal, bm_price)

# --- CHECK 8: InventoryLink composite PK ---
il_menu_pk = InventoryLink.model_fields["menu_id"].primary_key
il_branch_pk = InventoryLink.model_fields["branch_id"].primary_key
check(
    "InventoryLink composite PK (menu_id + branch_id)",
    il_menu_pk and il_branch_pk,
    f"menu_id_pk={il_menu_pk} branch_id_pk={il_branch_pk}",
)

# --- CHECK 9: no Relationship() fields ---
for name, cls in [
    ("Variant", Variant), ("ItemAlias", ItemAlias),
    ("BranchMenu", BranchMenu), ("InventoryLink", InventoryLink),
]:
    rels = getattr(cls, "__sqlmodel_relationships__", {})
    check(f"{name} has no relationships", len(rels) == 0, len(rels))

# --- CHECK 10: DDL compiles ONLY for Variant + ItemAlias
#     (BranchMenu / InventoryLink cannot compile until branches exists — Phase 3) ---
for name, cls in [("Variant", Variant), ("ItemAlias", ItemAlias)]:
    try:
        CreateTable(cls.__table__).compile(dialect=postgresql.dialect())
        check(f"{name} DDL compiles", True)
    except Exception as exc:  # noqa: BLE001
        check(f"{name} DDL compiles", False, f"{type(exc).__name__}: {str(exc)[:80]}")

# --- CHECK 11: Variant DDL uses NUMERIC(10, 2) ---
v_ddl = str(CreateTable(Variant.__table__).compile(dialect=postgresql.dialect()))
check("Variant DDL has NUMERIC(10, 2)", "NUMERIC(10, 2)" in v_ddl, None)

# --- summary ---
print()
print("=" * 60)
failed = [r for r in results if r[1] == "FAIL"]
print(f"PHASE 2c SELF-CHECK  —  {len(results) - len(failed)}/{len(results)} passed")
print("=" * 60)
if failed:
    print("FAILED CHECKS:")
    for name, _, got in failed:
        print(f"  - {name}  (got: {got})")
    print()
    print("RESULT: NEEDS FIX")
    sys.exit(1)
else:
    print("RESULT: READY FOR 2d")
    sys.exit(0)
