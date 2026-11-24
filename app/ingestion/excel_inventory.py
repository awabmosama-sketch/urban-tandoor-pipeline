"""Inventory workbook parsing: Excel -> JSON.

Populates six collections: suppliers, ingredients, branches, branch_stock,
recipes and stock_movements.

BranchStock computed fields are derived in Python (on_hand, available,
suggested_buy, stock_status, stock_value_pkr) — never read from the workbook's
stale formula columns. Recipes drop the workbook's PECHS_*/Gulshan_* formula
columns because those are derived at query time by the API.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time
from pathlib import Path

import pandas as pd

from app.config import get_settings
from app.ingestion._parsers import (
    _null,
    _opt_str,
    _req_dec,
    _req_float,
    _req_int,
    _req_str,
)
from app.ingestion.json_store import write_collection

INVENTORY_WORKBOOK_FILENAME = "Urban_Tandoor_Two_Branch_Inventory_Dataset.xlsx"


def _workbook_path() -> Path:
    path = Path(get_settings().data_dir) / INVENTORY_WORKBOOK_FILENAME
    if not path.exists():
        raise FileNotFoundError(
            f"Copy the workbook to {path.resolve()} before exporting inventory JSON."
        )
    return path


def _load_sheet(xls: pd.ExcelFile, sheet: str) -> pd.DataFrame:
    df = pd.read_excel(xls, sheet_name=sheet, dtype=object)
    df.columns = [str(c).strip() for c in df.columns]
    return df


def parse_suppliers(df: pd.DataFrame) -> list[dict]:
    return [
        {
            "supplier_id": _req_str(r, "Supplier_ID"),
            "supplier_name": _req_str(r, "Supplier_Name"),
            "supply_category": _req_str(r, "Supply_Category"),
            "contact": _opt_str(r, "Contact"),
            "verification": _req_str(r, "Verification"),
        }
        for r in df.to_dict(orient="records")
    ]


def parse_ingredients(df: pd.DataFrame) -> list[dict]:
    return [
        {
            "ingredient_id": _req_str(r, "Ingredient_ID"),
            "ingredient_name": _req_str(r, "Ingredient_Name"),
            "category": _req_str(r, "Category"),
            "unit": _req_str(r, "Unit"),
            "unit_cost_pkr": float(_req_dec(r, "Unit_Cost_PKR")),
            "default_reorder": _req_float(r, "Default_Reorder"),
            "default_target": _req_float(r, "Default_Target"),
            "supplier_id": _opt_str(r, "Supplier_ID"),
            "status": _req_str(r, "Status") if _null(r.get("Status")) else "Active",
        }
        for r in df.to_dict(orient="records")
    ]


def parse_branches(df: pd.DataFrame) -> list[dict]:
    return [
        {
            "branch_id": _req_str(r, "Branch_ID"),
            "branch_name": _req_str(r, "Branch_Name"),
            "address_demo": _opt_str(r, "Address_Demo"),
            "tables_count": _req_int(r, "Tables"),
            "seats": _req_int(r, "Seats"),
            "hours": _req_str(r, "Hours"),
            "status": _req_str(r, "Status"),
        }
        for r in df.to_dict(orient="records")
    ]


def _compute_branch_stock_row(row: dict) -> dict:
    opening = _req_float(row, "Opening")
    received = _req_float(row, "Received")
    consumed = _req_float(row, "Consumed")
    wastage = _req_float(row, "Wastage")
    adjustment = _req_float(row, "Adjustment")
    reserved = _req_float(row, "Reserved")
    reorder = _req_float(row, "Reorder_Level")
    target = _req_float(row, "Target_Stock")
    unit_cost = _req_dec(row, "Unit_Cost_PKR")

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
    stock_value = max(0.0, on_hand) * float(unit_cost)

    raw_updated = _null(row.get("Updated_At"))
    if raw_updated:
        try:
            day = date.fromisoformat(str(raw_updated)[:10])
            snapshot_at = datetime.combine(day, time.min, tzinfo=UTC)
        except Exception:
            snapshot_at = datetime.now(UTC)
    else:
        snapshot_at = datetime.now(UTC)

    return {
        "branch_id": _req_str(row, "Branch_ID"),
        "ingredient_id": _req_str(row, "Ingredient_ID"),
        "ingredient_name": _req_str(row, "Ingredient_Name"),
        "category": _req_str(row, "Category"),
        "unit": _req_str(row, "Unit"),
        "opening": opening,
        "received": received,
        "consumed": consumed,
        "wastage": wastage,
        "adjustment": adjustment,
        "reserved": reserved,
        "on_hand": on_hand,
        "available": available,
        "suggested_buy": suggested_buy,
        "stock_status": stock_status,
        "stock_value_pkr": stock_value,
        "reorder_level": reorder,
        "target_stock": target,
        "unit_cost_pkr": float(unit_cost),
        "snapshot_at": snapshot_at,
    }


def parse_branch_stock(df: pd.DataFrame) -> list[dict]:
    return [_compute_branch_stock_row(row) for row in df.to_dict(orient="records")]


def parse_recipes(df: pd.DataFrame) -> list[dict]:
    return [
        {
            "menu_id": _req_str(r, "Menu_ID"),
            "ingredient_id": _req_str(r, "Ingredient_ID"),
            "menu_item": _req_str(r, "Menu_Item"),
            "category": _req_str(r, "Category"),
            "qty_per_portion": _req_float(r, "Qty_Per_Portion"),
            "ingredient_name": _req_str(r, "Ingredient_Name"),
        }
        for r in df.to_dict(orient="records")
    ]


def parse_stock_movements(df: pd.DataFrame) -> list[dict]:
    rows: list[dict] = []
    for r in df.to_dict(orient="records"):
        raw_date = _req_str(r, "Movement_Date")
        try:
            movement_date = date.fromisoformat(str(raw_date)[:10])
        except Exception as exc:
            raise ValueError(f"Invalid Movement_Date {raw_date!r}: {exc}") from exc
        rows.append(
            {
                "movement_id": _req_str(r, "Movement_ID"),
                "movement_date": movement_date,
                "branch_id": _req_str(r, "Branch_ID"),
                "ingredient_id": _req_str(r, "Ingredient_ID"),
                "movement_type": _req_str(r, "Movement_Type"),
                "qty_signed": _req_float(r, "Qty_Signed"),
                "unit": _req_str(r, "Unit"),
                "reference": _opt_str(r, "Reference"),
                "reason": _opt_str(r, "Reason"),
                "data_type": _req_str(r, "Data_Type") if _null(r.get("Data_Type")) else "Demo",
            }
        )
    return rows


SHEET_SPECS = (
    ("suppliers", "Suppliers", parse_suppliers),
    ("ingredients", "Ingredients", parse_ingredients),
    ("branches", "Branches", parse_branches),
    ("branch_stock", "Branch_Stock", parse_branch_stock),
    ("recipes", "Recipes", parse_recipes),
    ("stock_movements", "Stock_Movements", parse_stock_movements),
)


def build_inventory_datasets() -> dict[str, list[dict]]:
    """Parse every inventory sheet into ``{collection_name: [documents]}``."""
    xls = pd.ExcelFile(_workbook_path())
    return {
        name: parser(_load_sheet(xls, sheet))
        for name, sheet, parser in SHEET_SPECS
    }


def export_inventory_json() -> dict[str, int]:
    """Write the six inventory collections to ``data/json/``."""
    datasets = build_inventory_datasets()
    for name, documents in datasets.items():
        write_collection(name, documents)
    return {name: len(documents) for name, documents in datasets.items()}


async def ingest_inventory(db=None) -> dict[str, int]:
    """Export the workbook to JSON, then load that JSON into MongoDB."""
    from app.database import get_db
    from app.ingestion.json_ingest import ingest_json_domain

    export_inventory_json()
    return await ingest_json_domain(db or get_db(), "inventory")


__all__ = [
    "INVENTORY_WORKBOOK_FILENAME",
    "build_inventory_datasets",
    "export_inventory_json",
    "ingest_inventory",
]
