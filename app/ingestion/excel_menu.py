"""Menu catalog parsing: ``Urban_Tandoor_Complete_Menu_Catalog.xlsx`` -> JSON.

The workbook has 12 menu-domain sheets. Each sheet is parsed into plain Python
dicts with API field names, then written to ``data/json/<collection>.json``.
No database driver is used here; ``app.ingestion.json_ingest`` loads the JSON
into MongoDB.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from app.config import get_settings
from app.ingestion._parsers import (
    _null,
    _opt_dec,
    _opt_float,
    _opt_int,
    _opt_str,
    _req_bool,
    _req_dec,
    _req_float,
    _req_int,
    _req_str,
)
from app.ingestion.json_store import write_collection

MENU_WORKBOOK_FILENAME = "Urban_Tandoor_Complete_Menu_Catalog.xlsx"


# ---------------------------------------------------------------------------
# Workbook plumbing
# ---------------------------------------------------------------------------
def _workbook_path() -> Path:
    path = Path(get_settings().data_dir) / MENU_WORKBOOK_FILENAME
    if not path.exists():
        raise FileNotFoundError(
            f"Copy the workbook to {path.resolve()} before exporting menu JSON."
        )
    return path


def _load_sheet(xls: pd.ExcelFile, sheet: str) -> pd.DataFrame:
    df = pd.read_excel(xls, sheet_name=sheet, dtype=object)
    df.columns = [str(c).strip() for c in df.columns]
    return df


def _allergen_verified(row, key):
    """Allergen_Verified uses Yes/No *and* the domain value ``Unverified``."""
    value = _null(row.get(key))
    if isinstance(value, bool):
        return value
    if value is None:
        raise ValueError(f"Missing required bool {key}: {row}")
    text = str(value).strip().lower()
    if text in ("yes", "verified"):
        return True
    if text in ("no", "unverified"):
        return False
    raise ValueError(f"Invalid allergen verification {key}={value!r}: {row}")


# ---------------------------------------------------------------------------
# One parser per sheet
# ---------------------------------------------------------------------------
def parse_categories(df: pd.DataFrame) -> list[dict]:
    return [
        {
            "category_id": _req_str(r, "Category_ID"),
            "category_name": _req_str(r, "Category_Name"),
            "sort_order": _req_int(r, "Sort_Order"),
            "status": _req_str(r, "Status"),
            "customer_description": _opt_str(r, "Customer_Description"),
        }
        for r in df.to_dict(orient="records")
    ]


def parse_menu_items(df: pd.DataFrame) -> list[dict]:
    now = datetime.now(UTC)
    return [
        {
            "menu_id": _req_str(r, "Menu_ID"),
            "item_name": _req_str(r, "Item_Name"),
            "category_id": _req_str(r, "Category_ID"),
            "category": _req_str(r, "Category"),
            "description": _opt_str(r, "Description"),
            "base_price_pkr": float(_req_dec(r, "Base_Price_PKR")),
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
            "updated_at": now,
        }
        for r in df.to_dict(orient="records")
    ]


def parse_variants(df: pd.DataFrame) -> list[dict]:
    return [
        {
            "variant_id": _req_str(r, "Variant_ID"),
            "menu_id": _req_str(r, "Menu_ID"),
            "variant_name": _req_str(r, "Variant_Name"),
            "price_pkr": float(_req_dec(r, "Price_PKR")),
            "recipe_multiplier_est": _req_float(r, "Recipe_Multiplier_Est"),
            "shown_in_menu": _req_bool(r, "Shown_In_Menu"),
            "approved_for_orders": _req_bool(r, "Approved_For_Orders"),
            "operational_notes": _opt_str(r, "Operational_Notes"),
        }
        for r in df.to_dict(orient="records")
    ]


def parse_addons(df: pd.DataFrame) -> list[dict]:
    return [
        {
            "addon_id": _req_str(r, "Addon_ID"),
            "addon_name": _req_str(r, "Addon_Name"),
            "price_pkr": float(_req_dec(r, "Price_PKR")),
            "category": _req_str(r, "Category"),
            "allergen_hint": _opt_str(r, "Allergen_Hint"),
            "ingredient_id": _opt_str(r, "Ingredient_ID"),
            "qty_ingredient_units": _opt_float(r, "Qty_Ingredient_Units"),
            "shown_in_menu": _req_bool(r, "Shown_In_Menu"),
            "order_status": _req_str(r, "Order_Status"),
        }
        for r in df.to_dict(orient="records")
    ]


def parse_item_addons(df: pd.DataFrame) -> list[dict]:
    return [
        {
            "mapping_id": _req_str(r, "Mapping_ID"),
            "menu_id": _req_str(r, "Menu_ID"),
            "addon_id": _req_str(r, "Addon_ID"),
            "selectable": _req_bool(r, "Selectable"),
            "operational_notes": _opt_str(r, "Operational_Notes"),
        }
        for r in df.to_dict(orient="records")
    ]


def parse_aliases(df: pd.DataFrame) -> list[dict]:
    return [
        {
            "alias_id": _req_str(r, "Alias_ID"),
            "menu_id": _req_str(r, "Menu_ID"),
            "customer_phrase": _req_str(r, "Customer_Phrase"),
            "language": _req_str(r, "Language"),
            "alias_notes": _opt_str(r, "Alias_Notes"),
        }
        for r in df.to_dict(orient="records")
    ]


def parse_branch_menu(df: pd.DataFrame) -> list[dict]:
    return [
        {
            "branch_menu_id": _req_str(r, "Branch_Menu_ID"),
            "branch_id": _req_str(r, "Branch_ID"),
            "branch_name": _req_str(r, "Branch_Name"),
            "menu_id": _req_str(r, "Menu_ID"),
            "enabled_for_order": _req_bool(r, "Enabled_For_Order"),
            "price_pkr": float(_req_dec(r, "Price_PKR")),
            "base_variant_orderable": _req_bool(r, "Base_Variant_Orderable"),
            "stock_decision": _req_str(r, "Stock_Decision"),
            "snapshot_max_portions": _opt_int(r, "Snapshot_Max_Portions"),
            "notes": _opt_str(r, "Notes"),
        }
        for r in df.to_dict(orient="records")
    ]


def parse_inventory_links(df: pd.DataFrame) -> list[dict]:
    return [
        {
            "menu_id": _req_str(r, "Menu_ID"),
            "branch_id": _req_str(r, "Branch_ID"),
            "recipe_linked": _req_bool(r, "Recipe_Linked"),
            "snapshot_max_portions": _opt_int(r, "Snapshot_Max_Portions"),
            "recipe_link_status": _req_str(r, "Recipe_Link_Status"),
            "runtime_check_policy": _req_str(r, "Runtime_Check_Policy"),
        }
        for r in df.to_dict(orient="records")
    ]


def parse_deals(df: pd.DataFrame) -> list[dict]:
    return [
        {
            "deal_id": _req_str(r, "Deal_ID"),
            "deal_name": _req_str(r, "Deal_Name"),
            "deal_type": _req_str(r, "Deal_Type"),
            "description": _req_str(r, "Description"),
            "deal_price_pkr": float(_req_dec(r, "Deal_Price_PKR")),
            "currency": _req_str(r, "Currency"),
            "approval_status": _req_str(r, "Approval_Status"),
            "branches": _req_str(r, "Branches"),
            "service_window": _req_str(r, "Service_Window"),
            "min_spend_pkr": (
                None if _opt_dec(r, "Min_Spend_PKR") is None
                else float(_opt_dec(r, "Min_Spend_PKR"))
            ),
            "stack_bank_discount": _req_bool(r, "Stack_Bank_Discount"),
            "policy_notes": _opt_str(r, "Policy_Notes"),
        }
        for r in df.to_dict(orient="records")
    ]


def parse_deal_items(df: pd.DataFrame) -> list[dict]:
    return [
        {
            "deal_id": _req_str(r, "Deal_ID"),
            "menu_id": _req_str(r, "Menu_ID"),
            "item_name": _req_str(r, "Item_Name"),
            "qty": _req_int(r, "Qty"),
            "variant_id": _req_str(r, "Variant_ID"),
        }
        for r in df.to_dict(orient="records")
    ]


def parse_allergen_guide(df: pd.DataFrame) -> list[dict]:
    return [
        {
            "allergen_code": _req_str(r, "Allergen_Code"),
            "display_name": _req_str(r, "Display_Name"),
            "status": _req_str(r, "Status"),
            "use_policy": _req_str(r, "Use_Policy"),
        }
        for r in df.to_dict(orient="records")
    ]


def parse_service_rules(df: pd.DataFrame) -> list[dict]:
    return [
        {
            "rule_id": _req_str(r, "Rule_ID"),
            "rule_name": _req_str(r, "Rule_Name"),
            "value": _req_str(r, "Value"),
            "applies_to": _req_str(r, "Applies_To"),
            "verification_status": _req_str(r, "Verification_Status"),
            "comment": _opt_str(r, "Comment"),
        }
        for r in df.to_dict(orient="records")
    ]


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------
SHEET_SPECS = (
    ("categories", "Categories", parse_categories),
    ("menu_items", "Menu_Items", parse_menu_items),
    ("variants", "Variants", parse_variants),
    ("addons", "Addons", parse_addons),
    ("item_addons", "Item_Addons", parse_item_addons),
    ("item_aliases", "Item_Aliases", parse_aliases),
    ("branch_menu", "Branch_Menu", parse_branch_menu),
    ("inventory_links", "Inventory_Links", parse_inventory_links),
    ("deals", "Deals", parse_deals),
    ("deal_items", "Deal_Items", parse_deal_items),
    ("allergen_guide", "Allergen_Guide", parse_allergen_guide),
    ("service_rules", "Service_Rules", parse_service_rules),
)


def build_menu_datasets() -> dict[str, list[dict]]:
    """Parse every menu sheet into ``{collection_name: [documents]}``."""
    xls = pd.ExcelFile(_workbook_path())
    return {
        name: parser(_load_sheet(xls, sheet))
        for name, sheet, parser in SHEET_SPECS
    }


def export_menu_json() -> dict[str, int]:
    """Write the 12 menu collections to ``data/json/`` and return counts."""
    datasets = build_menu_datasets()
    for name, documents in datasets.items():
        write_collection(name, documents)
    return {name: len(documents) for name, documents in datasets.items()}


async def ingest_menu_catalog(db=None) -> dict[str, int]:
    """Export the workbook to JSON, then load that JSON into MongoDB."""
    from app.database import get_db
    from app.ingestion.json_ingest import ingest_json_domain

    export_menu_json()
    return await ingest_json_domain(db or get_db(), "menu")


__all__ = [
    "MENU_WORKBOOK_FILENAME",
    "build_menu_datasets",
    "export_menu_json",
    "ingest_menu_catalog",
]
