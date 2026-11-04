"""
Inventory workbook ingestion. Populates: suppliers, ingredients, branches,
branch_stock, recipes, stock_movements.

BranchStock computed fields are derived in Python (on_hand, available,
suggested_buy, stock_status, stock_value_pkr) — never read from the workbook's
stale formula columns.

Recipes DROPS the workbook's PECHS_*/Gulshan_* formula columns — those are
derived at query time by the API.
"""
from __future__ import annotations
import pandas as pd
from datetime import date, datetime, time, timezone
from decimal import Decimal
from pathlib import Path
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.ingestion._parsers import (
    _null, _req_str, _opt_str, _req_int, _opt_int,
    _req_float, _opt_float, _req_dec, _opt_dec, _req_bool,
)
from app.ingestion._upsert import upsert_rows
from app.models import (
    Supplier, Ingredient, Branch, BranchStock, Recipe, StockMovement,
)

INVENTORY_WORKBOOK_FILENAME = "Urban_Tandoor_Two_Branch_Inventory_Dataset.xlsx"
_DROP_RECIPE_COLUMNS = {
    "PECHS_Available", "PECHS_Max_Portions",
    "Gulshan_Available", "Gulshan_Max_Portions",
}


def _workbook_path() -> Path:
    p = Path(get_settings().data_dir) / INVENTORY_WORKBOOK_FILENAME
    if not p.exists():
        raise FileNotFoundError(
            f"Copy the workbook to {p.resolve()} before running Phase 7 ingestion."
        )
    return p


def _load_sheet(xls: pd.ExcelFile, sheet: str) -> pd.DataFrame:
    df = pd.read_excel(xls, sheet_name=sheet, dtype=object)
    df.columns = [str(c).strip() for c in df.columns]
    return df


async def upsert_suppliers(session, df) -> int:
    rows = [{
        "supplier_id": _req_str(r, "Supplier_ID"),
        "supplier_name": _req_str(r, "Supplier_Name"),
        "supply_category": _req_str(r, "Supply_Category"),
        "contact": _opt_str(r, "Contact"),
        "verification": _req_str(r, "Verification"),
    } for r in df.to_dict(orient="records")]
    return await upsert_rows(session, Supplier, rows, ["supplier_id"])


async def upsert_ingredients(session, df) -> int:
    rows = [{
        "ingredient_id": _req_str(r, "Ingredient_ID"),
        "ingredient_name": _req_str(r, "Ingredient_Name"),
        "category": _req_str(r, "Category"),
        "unit": _req_str(r, "Unit"),
        "unit_cost_pkr": _req_dec(r, "Unit_Cost_PKR"),
        "default_reorder": _req_float(r, "Default_Reorder"),
        "default_target": _req_float(r, "Default_Target"),
        "supplier_id": _opt_str(r, "Supplier_ID"),
        "status": _req_str(r, "Status") if _null(r.get("Status")) else "Active",
    } for r in df.to_dict(orient="records")]
    return await upsert_rows(session, Ingredient, rows, ["ingredient_id"])


async def upsert_branches(session, df) -> int:
    rows = [{
        "branch_id": _req_str(r, "Branch_ID"),
        "branch_name": _req_str(r, "Branch_Name"),
        "address_demo": _opt_str(r, "Address_Demo"),
        "tables_count": _req_int(r, "Tables"),
        "seats": _req_int(r, "Seats"),
        "hours": _req_str(r, "Hours"),
        "status": _req_str(r, "Status"),
    } for r in df.to_dict(orient="records")]
    return await upsert_rows(session, Branch, rows, ["branch_id"])


def _compute_branch_stock_row(r: dict) -> dict:
    """Given a source row dict, return a BranchStock row dict with ALL 20
    fields (raw inputs + computed + snapshot_at), on_hand via Python formula."""
    opening   = _req_float(r, "Opening")
    received  = _req_float(r, "Received")
    consumed  = _req_float(r, "Consumed")
    wastage   = _req_float(r, "Wastage")
    adjustment = _req_float(r, "Adjustment")
    reserved  = _req_float(r, "Reserved")
    reorder   = _req_float(r, "Reorder_Level")
    target    = _req_float(r, "Target_Stock")
    unit_cost = _req_dec(r, "Unit_Cost_PKR")

    on_hand = opening + received - consumed - wastage + adjustment
    available = max(0.0, on_hand - reserved)
    suggested_buy = max(0.0, target - on_hand) if on_hand <= reorder else 0.0
    if on_hand < 0:
        stock_status = "DATA ERROR"
    elif available <= 0:
        stock_status = "OUT OF STOCK"
    elif on_hand <= reorder:
        stock_status = "REORDER"
    else:
        stock_status = "OK"
    stock_value = Decimal(str(max(0.0, on_hand))) * unit_cost

    raw_updated = _null(r.get("Updated_At"))
    if raw_updated:
        try:
            d = date.fromisoformat(str(raw_updated)[:10])
            snapshot_at = datetime.combine(d, time.min, tzinfo=timezone.utc)
        except Exception:
            snapshot_at = datetime.now(timezone.utc)
    else:
        snapshot_at = datetime.now(timezone.utc)

    return {
        "branch_id": _req_str(r, "Branch_ID"),
        "ingredient_id": _req_str(r, "Ingredient_ID"),
        "ingredient_name": _req_str(r, "Ingredient_Name"),
        "category": _req_str(r, "Category"),
        "unit": _req_str(r, "Unit"),
        "opening": opening, "received": received, "consumed": consumed,
        "wastage": wastage, "adjustment": adjustment, "reserved": reserved,
        "on_hand": on_hand, "available": available,
        "suggested_buy": suggested_buy, "stock_status": stock_status,
        "stock_value_pkr": stock_value,
        "reorder_level": reorder, "target_stock": target,
        "unit_cost_pkr": unit_cost, "snapshot_at": snapshot_at,
    }


async def upsert_branch_stock(session, df) -> int:
    rows = [_compute_branch_stock_row(r) for r in df.to_dict(orient="records")]
    return await upsert_rows(
        session, BranchStock, rows, ["branch_id", "ingredient_id"],
    )


async def upsert_recipes(session, df) -> int:
    # Defensive: if the DataFrame somehow has the dropped columns, ignore them.
    rows = [{
        "menu_id": _req_str(r, "Menu_ID"),
        "ingredient_id": _req_str(r, "Ingredient_ID"),
        "menu_item": _req_str(r, "Menu_Item"),
        "category": _req_str(r, "Category"),
        "qty_per_portion": _req_float(r, "Qty_Per_Portion"),
        "ingredient_name": _req_str(r, "Ingredient_Name"),
    } for r in df.to_dict(orient="records")]
    return await upsert_rows(session, Recipe, rows, ["menu_id", "ingredient_id"])


async def upsert_stock_movements(session, df) -> int:
    rows = []
    for r in df.to_dict(orient="records"):
        raw_date = _req_str(r, "Movement_Date")
        try:
            mv_date = date.fromisoformat(str(raw_date)[:10])
        except Exception as exc:
            raise ValueError(f"Invalid Movement_Date {raw_date!r}: {exc}")
        rows.append({
            "movement_id": _req_str(r, "Movement_ID"),
            "movement_date": mv_date,
            "branch_id": _req_str(r, "Branch_ID"),
            "ingredient_id": _req_str(r, "Ingredient_ID"),
            "movement_type": _req_str(r, "Movement_Type"),
            "qty_signed": _req_float(r, "Qty_Signed"),
            "unit": _req_str(r, "Unit"),
            "reference": _opt_str(r, "Reference"),
            "reason": _opt_str(r, "Reason"),
            "data_type": _req_str(r, "Data_Type") if _null(r.get("Data_Type")) else "Demo",
        })
    return await upsert_rows(session, StockMovement, rows, ["movement_id"])


async def ingest_inventory(session: AsyncSession) -> dict[str, int]:
    path = _workbook_path()
    xls = pd.ExcelFile(path)
    counts: dict[str, int] = {}
    async def step(name, sheet, fn):
        df = _load_sheet(xls, sheet)
        counts[name] = await fn(session, df)
    # FK ORDER (do not reorder):
    await step("suppliers", "Suppliers", upsert_suppliers)
    await step("ingredients", "Ingredients", upsert_ingredients)
    await step("branches", "Branches", upsert_branches)
    await step("branch_stock", "Branch_Stock", upsert_branch_stock)
    await step("recipes", "Recipes", upsert_recipes)
    await step("stock_movements", "Stock_Movements", upsert_stock_movements)
    return counts
