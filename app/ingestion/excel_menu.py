"""Menu catalog ingestion from ``Urban_Tandoor_Complete_Menu_Catalog.xlsx``.

Phase 6 ingests the 12 menu-domain sheets in FK-safe order. Workbook headers are
mapped to model attribute names and every cell is cleaned explicitly; no pandas
``to_sql`` is used.

Two schema realities require small, documented deviations from the literal
Phase 6 brief:

* ``Menu_Items.Allergen_Verified`` stores ``"Unverified"`` rather than Yes/No.
  It is mapped to ``False`` (the item is simply not verified yet).
* ``addons.ingredient_id`` and the ``branch_menu``/``inventory_links`` branch
  FKs reference ``ingredients``/``branches``, which are only populated in
  Phase 7. To keep referential integrity valid *now* without touching the
  inventory workbook, minimal placeholder parent rows are inserted for the
  IDs the menu workbook references. They are inserted with
  ``ON CONFLICT DO NOTHING`` so Phase 7 (and later re-runs) can safely
  overwrite them with real values.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pandas as pd
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.ingestion._upsert import upsert_rows
from app.models import (
    Addon,
    AllergenGuide,
    Branch,
    BranchMenu,
    Category,
    Deal,
    DealItem,
    Ingredient,
    InventoryLink,
    ItemAddon,
    ItemAlias,
    MenuItem,
    ServiceRule,
    Variant,
)

MENU_WORKBOOK_FILENAME = "Urban_Tandoor_Complete_Menu_Catalog.xlsx"


# ---------------------------------------------------------------------------
# Workbook plumbing
# ---------------------------------------------------------------------------
def _workbook_path() -> Path:
    p = Path(get_settings().data_dir) / MENU_WORKBOOK_FILENAME
    if not p.exists():
        raise FileNotFoundError(
            f"Copy the workbook to {p.resolve()} before running Phase 6 ingestion."
        )
    return p


def _load_sheet(xls: pd.ExcelFile, sheet: str) -> pd.DataFrame:
    df = pd.read_excel(xls, sheet_name=sheet, dtype=object)
    # Normalize column names (already expected to match, but strip whitespace)
    df.columns = [str(c).strip() for c in df.columns]
    return df


# ---------------------------------------------------------------------------
# Cell cleaning helpers
# ---------------------------------------------------------------------------
def _null(v):
    if v is None:
        return None
    if isinstance(v, float) and v != v:  # NaN
        return None
    if isinstance(v, str):
        s = v.strip()
        if s == "" or s.lower() == "none":
            return None
        return s
    return v


def _req_str(r, k):
    v = _null(r.get(k))
    if v is None:
        raise ValueError(f"Missing required string {k}: {r}")
    return str(v)


def _opt_str(r, k):
    v = _null(r.get(k))
    return None if v is None else str(v)


def _req_int(r, k):
    v = _null(r.get(k))
    if v is None:
        raise ValueError(f"Missing required int {k}: {r}")
    return int(float(v))


def _opt_int(r, k):
    v = _null(r.get(k))
    return None if v is None else int(float(v))


def _req_float(r, k):
    v = _null(r.get(k))
    if v is None:
        raise ValueError(f"Missing required float {k}: {r}")
    return float(v)


def _opt_float(r, k):
    v = _null(r.get(k))
    return None if v is None else float(v)


def _req_dec(r, k):
    v = _null(r.get(k))
    if v is None:
        raise ValueError(f"Missing required decimal {k}: {r}")
    return Decimal(str(v))


def _opt_dec(r, k):
    v = _null(r.get(k))
    return None if v is None else Decimal(str(v))


def _req_bool(r, k):
    v = _null(r.get(k))
    if isinstance(v, bool):
        return v
    if v is None:
        raise ValueError(f"Missing required bool {k}: {r}")
    s = str(v).strip().lower()
    if s == "yes":
        return True
    if s == "no":
        return False
    raise ValueError(f"Invalid bool {k}={v!r} — must be Yes/No: {r}")


def _allergen_verified(r, k):
    """Allergen_Verified uses Yes/No *and* the domain value ``Unverified``."""
    v = _null(r.get(k))
    if isinstance(v, bool):
        return v
    if v is None:
        raise ValueError(f"Missing required bool {k}: {r}")
    s = str(v).strip().lower()
    if s in ("yes", "verified"):
        return True
    if s in ("no", "unverified"):
        return False
    raise ValueError(f"Invalid allergen verification {k}={v!r}: {r}")


# ---------------------------------------------------------------------------
# Placeholder parent rows (see module docstring)
# ---------------------------------------------------------------------------
async def _ensure_ingredient_stubs(
    session: AsyncSession, ingredient_ids: list[str]
) -> None:
    if not ingredient_ids:
        return
    table = Ingredient.__table__
    existing = set(
        (
            await session.execute(
                select(table.c.ingredient_id).where(
                    table.c.ingredient_id.in_(ingredient_ids)
                )
            )
        )
        .scalars()
        .all()
    )
    missing = [i for i in ingredient_ids if i not in existing]
    if not missing:
        return
    rows = [
        {
            "ingredient_id": ingredient_id,
            "ingredient_name": f"{ingredient_id} (pending inventory import)",
            "category": "Unmapped",
            "unit": "unit",
            "unit_cost_pkr": Decimal("0.00"),
            "default_reorder": 0.0,
            "default_target": 0.0,
            "supplier_id": None,
            "status": "Placeholder",
        }
        for ingredient_id in missing
    ]
    await session.execute(
        pg_insert(table).values(rows).on_conflict_do_nothing(
            index_elements=["ingredient_id"]
        )
    )


async def _ensure_branch_stubs(
    session: AsyncSession, branches: dict[str, str]
) -> None:
    if not branches:
        return
    table = Branch.__table__
    existing = set(
        (
            await session.execute(
                select(table.c.branch_id).where(
                    table.c.branch_id.in_(list(branches))
                )
            )
        )
        .scalars()
        .all()
    )
    missing = [b for b in branches if b not in existing]
    if not missing:
        return
    rows = [
        {
            "branch_id": branch_id,
            "branch_name": branches[branch_id],
            "address_demo": None,
            "tables_count": 0,
            "seats": 0,
            "hours": "24/7",
            "status": "Active",
        }
        for branch_id in missing
    ]
    await session.execute(
        pg_insert(table).values(rows).on_conflict_do_nothing(
            index_elements=["branch_id"]
        )
    )


# ---------------------------------------------------------------------------
# One upsert function per sheet
# ---------------------------------------------------------------------------
async def upsert_categories(session: AsyncSession, df: pd.DataFrame) -> int:
    rows = []
    for r in df.to_dict(orient="records"):
        rows.append(
            {
                "category_id": _req_str(r, "Category_ID"),
                "category_name": _req_str(r, "Category_Name"),
                "sort_order": _req_int(r, "Sort_Order"),
                "status": _req_str(r, "Status"),
                "customer_description": _opt_str(r, "Customer_Description"),
            }
        )
    return await upsert_rows(session, Category, rows, ["category_id"])


async def upsert_menu_items(session: AsyncSession, df: pd.DataFrame) -> int:
    rows = []
    now = datetime.now(timezone.utc)
    for r in df.to_dict(orient="records"):
        rows.append(
            {
                "menu_id": _req_str(r, "Menu_ID"),
                "item_name": _req_str(r, "Item_Name"),
                "category_id": _req_str(r, "Category_ID"),
                "category": _req_str(r, "Category"),
                "description": _opt_str(r, "Description"),
                "base_price_pkr": _req_dec(r, "Base_Price_PKR"),
                "currency": _req_str(r, "Currency"),
                "item_type": _req_str(r, "Item_Type"),
                "catalog_status": _req_str(r, "Catalog_Status"),
                "recipe_linked": _req_bool(r, "Recipe_Linked"),
                "prep_time_min": _req_int(r, "Prep_Time_Min"),
                "dietary_hint": _opt_str(r, "Dietary_Hint"),
                "allergen_hint": _opt_str(r, "Allergen_Hint"),
                "allergen_verified": _allergen_verified(r, "Allergen_Verified"),
                "service_window": _req_str(r, "Service_Window"),
                "upsell_eligible": _req_bool(r, "Upsell_Eligible"),
                "slug": _req_str(r, "Slug"),
                "data_provenance": _req_str(r, "Data_Provenance"),
                # Needed because the Core upsert bypasses the model's Python
                # default_factory; the column is NOT NULL without a DB default.
                "updated_at": now,
            }
        )
    return await upsert_rows(session, MenuItem, rows, ["menu_id"])


async def upsert_variants(session: AsyncSession, df: pd.DataFrame) -> int:
    rows = []
    for r in df.to_dict(orient="records"):
        rows.append(
            {
                "variant_id": _req_str(r, "Variant_ID"),
                "menu_id": _req_str(r, "Menu_ID"),
                "variant_name": _req_str(r, "Variant_Name"),
                "price_pkr": _req_dec(r, "Price_PKR"),
                "recipe_multiplier_est": _req_float(r, "Recipe_Multiplier_Est"),
                "shown_in_menu": _req_bool(r, "Shown_In_Menu"),
                "approved_for_orders": _req_bool(r, "Approved_For_Orders"),
                "operational_notes": _opt_str(r, "Operational_Notes"),
            }
        )
    return await upsert_rows(session, Variant, rows, ["variant_id"])


async def upsert_addons(session: AsyncSession, df: pd.DataFrame) -> int:
    rows = []
    for r in df.to_dict(orient="records"):
        rows.append(
            {
                "addon_id": _req_str(r, "Addon_ID"),
                "addon_name": _req_str(r, "Addon_Name"),
                "price_pkr": _req_dec(r, "Price_PKR"),
                "category": _req_str(r, "Category"),
                "allergen_hint": _opt_str(r, "Allergen_Hint"),
                "ingredient_id": _opt_str(r, "Ingredient_ID"),
                "qty_ingredient_units": _opt_float(r, "Qty_Ingredient_Units"),
                "shown_in_menu": _req_bool(r, "Shown_In_Menu"),
                "order_status": _req_str(r, "Order_Status"),
            }
        )
    # Phase 7 supplies the full ingredient rows; these stubs keep the FK valid.
    ingredient_ids = sorted({row["ingredient_id"] for row in rows if row["ingredient_id"]})
    await _ensure_ingredient_stubs(session, ingredient_ids)
    return await upsert_rows(session, Addon, rows, ["addon_id"])


async def upsert_item_addons(session: AsyncSession, df: pd.DataFrame) -> int:
    rows = []
    for r in df.to_dict(orient="records"):
        rows.append(
            {
                "mapping_id": _req_str(r, "Mapping_ID"),
                "menu_id": _req_str(r, "Menu_ID"),
                "addon_id": _req_str(r, "Addon_ID"),
                "selectable": _req_bool(r, "Selectable"),
                "operational_notes": _opt_str(r, "Operational_Notes"),
            }
        )
    return await upsert_rows(session, ItemAddon, rows, ["mapping_id"])


async def upsert_aliases(session: AsyncSession, df: pd.DataFrame) -> int:
    rows = []
    for r in df.to_dict(orient="records"):
        rows.append(
            {
                "alias_id": _req_str(r, "Alias_ID"),
                "menu_id": _req_str(r, "Menu_ID"),
                "customer_phrase": _req_str(r, "Customer_Phrase"),
                "language": _req_str(r, "Language"),
                "alias_notes": _opt_str(r, "Alias_Notes"),
            }
        )
    return await upsert_rows(session, ItemAlias, rows, ["alias_id"])


async def upsert_branch_menu(session: AsyncSession, df: pd.DataFrame) -> int:
    rows = []
    branches: dict[str, str] = {}
    for r in df.to_dict(orient="records"):
        branch_id = _req_str(r, "Branch_ID")
        branches.setdefault(branch_id, _req_str(r, "Branch_Name"))
        rows.append(
            {
                "branch_menu_id": _req_str(r, "Branch_Menu_ID"),
                "branch_id": branch_id,
                "branch_name": _req_str(r, "Branch_Name"),
                "menu_id": _req_str(r, "Menu_ID"),
                "enabled_for_order": _req_bool(r, "Enabled_For_Order"),
                "price_pkr": _req_dec(r, "Price_PKR"),
                "base_variant_orderable": _req_bool(r, "Base_Variant_Orderable"),
                "stock_decision": _req_str(r, "Stock_Decision"),
                "snapshot_max_portions": _opt_int(r, "Snapshot_Max_Portions"),
                "notes": _opt_str(r, "Notes"),
            }
        )
    await _ensure_branch_stubs(session, branches)
    return await upsert_rows(session, BranchMenu, rows, ["branch_menu_id"])


async def upsert_inventory_links(session: AsyncSession, df: pd.DataFrame) -> int:
    rows = []
    for r in df.to_dict(orient="records"):
        rows.append(
            {
                "menu_id": _req_str(r, "Menu_ID"),
                "branch_id": _req_str(r, "Branch_ID"),
                "recipe_linked": _req_bool(r, "Recipe_Linked"),
                "snapshot_max_portions": _opt_int(r, "Snapshot_Max_Portions"),
                "recipe_link_status": _req_str(r, "Recipe_Link_Status"),
                "runtime_check_policy": _req_str(r, "Runtime_Check_Policy"),
            }
        )
    return await upsert_rows(
        session, InventoryLink, rows, ["menu_id", "branch_id"]
    )


async def upsert_deals(session: AsyncSession, df: pd.DataFrame) -> int:
    rows = []
    for r in df.to_dict(orient="records"):
        rows.append(
            {
                "deal_id": _req_str(r, "Deal_ID"),
                "deal_name": _req_str(r, "Deal_Name"),
                "deal_type": _req_str(r, "Deal_Type"),
                "description": _req_str(r, "Description"),
                "deal_price_pkr": _req_dec(r, "Deal_Price_PKR"),
                "currency": _req_str(r, "Currency"),
                "approval_status": _req_str(r, "Approval_Status"),
                "branches": _req_str(r, "Branches"),
                "service_window": _req_str(r, "Service_Window"),
                "min_spend_pkr": _opt_dec(r, "Min_Spend_PKR"),
                "stack_bank_discount": _req_bool(r, "Stack_Bank_Discount"),
                "policy_notes": _opt_str(r, "Policy_Notes"),
            }
        )
    return await upsert_rows(session, Deal, rows, ["deal_id"])


async def upsert_deal_items(session: AsyncSession, df: pd.DataFrame) -> int:
    rows = []
    for r in df.to_dict(orient="records"):
        rows.append(
            {
                "deal_id": _req_str(r, "Deal_ID"),
                "menu_id": _req_str(r, "Menu_ID"),
                "item_name": _req_str(r, "Item_Name"),
                "qty": _req_int(r, "Qty"),
                "variant_id": _req_str(r, "Variant_ID"),
            }
        )
    return await upsert_rows(
        session, DealItem, rows, ["deal_id", "menu_id", "variant_id"]
    )


async def upsert_allergen_guide(session: AsyncSession, df: pd.DataFrame) -> int:
    rows = []
    for r in df.to_dict(orient="records"):
        rows.append(
            {
                "allergen_code": _req_str(r, "Allergen_Code"),
                "display_name": _req_str(r, "Display_Name"),
                "status": _req_str(r, "Status"),
                "use_policy": _req_str(r, "Use_Policy"),
            }
        )
    return await upsert_rows(session, AllergenGuide, rows, ["allergen_code"])


async def upsert_service_rules(session: AsyncSession, df: pd.DataFrame) -> int:
    rows = []
    for r in df.to_dict(orient="records"):
        rows.append(
            {
                "rule_id": _req_str(r, "Rule_ID"),
                "rule_name": _req_str(r, "Rule_Name"),
                "value": _req_str(r, "Value"),
                "applies_to": _req_str(r, "Applies_To"),
                "verification_status": _req_str(r, "Verification_Status"),
                "comment": _opt_str(r, "Comment"),
            }
        )
    return await upsert_rows(session, ServiceRule, rows, ["rule_id"])


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------
async def ingest_menu_catalog(session: AsyncSession) -> dict[str, int]:
    path = _workbook_path()
    xls = pd.ExcelFile(path)
    counts: dict[str, int] = {}

    async def step(name, sheet, fn):
        df = _load_sheet(xls, sheet)
        counts[name] = await fn(session, df)

    # ORDER MATTERS (FK integrity):
    await step("categories", "Categories", upsert_categories)
    await step("menu_items", "Menu_Items", upsert_menu_items)
    await step("variants", "Variants", upsert_variants)
    await step("addons", "Addons", upsert_addons)
    await step("item_addons", "Item_Addons", upsert_item_addons)
    await step("item_aliases", "Item_Aliases", upsert_aliases)
    await step("branch_menu", "Branch_Menu", upsert_branch_menu)
    await step("inventory_links", "Inventory_Links", upsert_inventory_links)
    await step("deals", "Deals", upsert_deals)
    await step("deal_items", "Deal_Items", upsert_deal_items)
    await step("allergen_guide", "Allergen_Guide", upsert_allergen_guide)
    await step("service_rules", "Service_Rules", upsert_service_rules)
    return counts
