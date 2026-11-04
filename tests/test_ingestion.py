"""
Phase 6/7/8 verification. Row counts asserted against the source workbooks.

Why read source files: hard-coded numbers rot; deriving from source keeps
this file honest even if the workbooks change.
"""
from pathlib import Path

import pandas as pd
import pytest

from app.config import get_settings


MENU_XLSX = "Urban_Tandoor_Complete_Menu_Catalog.xlsx"
INV_XLSX = "Urban_Tandoor_Two_Branch_Inventory_Dataset.xlsx"


def _menu_count(sheet: str) -> int:
    p = Path(get_settings().data_dir) / MENU_XLSX
    return len(pd.read_excel(p, sheet_name=sheet))


def _inv_count(sheet: str) -> int:
    p = Path(get_settings().data_dir) / INV_XLSX
    return len(pd.read_excel(p, sheet_name=sheet))


@pytest.mark.asyncio
async def test_menu_tables(db):
    assert await db.count("categories") == _menu_count("Categories") == 8
    assert await db.count("menu_items") == _menu_count("Menu_Items") == 118
    assert await db.count("variants") == _menu_count("Variants") == 148
    assert await db.count("addons") == _menu_count("Addons") == 10
    assert await db.count("item_addons") == _menu_count("Item_Addons") == 284
    assert await db.count("item_aliases") == _menu_count("Item_Aliases") == 158
    assert await db.count("branch_menu") == _menu_count("Branch_Menu") == 236
    assert await db.count("inventory_links") == _menu_count("Inventory_Links") == 236
    assert await db.count("deals") == _menu_count("Deals") == 6
    assert await db.count("deal_items") == _menu_count("Deal_Items") == 15
    assert await db.count("allergen_guide") == _menu_count("Allergen_Guide") == 8
    assert await db.count("service_rules") == _menu_count("Service_Rules") == 7


@pytest.mark.asyncio
async def test_inventory_tables(db):
    assert await db.count("suppliers") == _inv_count("Suppliers") == 7
    assert await db.count("ingredients") == _inv_count("Ingredients") == 60
    assert await db.count("branches") == _inv_count("Branches") == 2
    assert await db.count("branch_stock") == _inv_count("Branch_Stock") == 120
    assert await db.count("recipes") == _inv_count("Recipes") == 130
    assert await db.count("stock_movements") == _inv_count("Stock_Movements") == 8


@pytest.mark.asyncio
async def test_document_tables(db):
    assert await db.count("source_documents") == 2
    assert await db.count("document_chunks") == 128
    # All chunks have embeddings
    assert await db.scalar(
        "SELECT COUNT(*) FROM document_chunks WHERE embedding IS NULL"
    ) == 0


@pytest.mark.asyncio
async def test_menu_item_spot(db):
    row = await db.first("SELECT * FROM menu_items WHERE menu_id='MENU001'")
    assert row["item_name"] == "Chicken Biryani"
    assert float(row["base_price_pkr"]) == 420.00
    assert row["catalog_status"] == "Active"
    assert row["prep_time_min"] == 35
    assert row["recipe_linked"] is True


@pytest.mark.asyncio
async def test_draft_item_spot(db):
    row = await db.first("SELECT * FROM menu_items WHERE menu_id='MENU033'")
    assert row["catalog_status"] == "Draft - Recipe Needed"
    assert row["recipe_linked"] is False


@pytest.mark.asyncio
async def test_branch_stock_computed_fields_populated(db):
    # No NULLs in computed fields
    n = await db.scalar("""
        SELECT COUNT(*) FROM branch_stock
        WHERE on_hand IS NULL OR available IS NULL OR suggested_buy IS NULL
           OR stock_status IS NULL OR stock_value_pkr IS NULL
    """)
    assert n == 0


@pytest.mark.asyncio
async def test_branch_stock_recompute_matches_db(db):
    """The decisive test: recompute on_hand from raw inputs, compare to DB."""
    rows = await db.all("""
        SELECT branch_id, ingredient_id, opening, received, consumed, wastage,
               adjustment, reserved, reorder_level, on_hand, available, stock_status
        FROM branch_stock
    """)
    assert len(rows) == 120
    mismatches = 0
    for r in rows:
        exp_on_hand = r["opening"] + r["received"] - r["consumed"] - r["wastage"] + r["adjustment"]
        exp_available = max(0.0, exp_on_hand - r["reserved"])
        if exp_on_hand < 0:
            exp_status = "DATA ERROR"
        elif exp_available <= 0:
            exp_status = "OUT OF STOCK"
        elif exp_on_hand <= r["reorder_level"]:
            exp_status = "REORDER"
        else:
            exp_status = "OK"
        if abs(r["on_hand"] - exp_on_hand) > 1e-6:
            mismatches += 1
        elif abs(r["available"] - exp_available) > 1e-6:
            mismatches += 1
        elif r["stock_status"] != exp_status:
            mismatches += 1
    assert mismatches == 0


@pytest.mark.asyncio
async def test_no_placeholder_rows(db):
    """Phase 6 placeholder cleanup from Phase 7."""
    assert await db.scalar(
        "SELECT COUNT(*) FROM branches WHERE tables_count = 0"
    ) == 0
    assert await db.scalar(
        "SELECT COUNT(*) FROM ingredients WHERE status = 'Placeholder'"
    ) == 0
