"""
Self-check for Phase 7. Run: python -m uv run python scripts/_selfcheck_7.py
Exits 0 on success, 1 on failure.
"""
import asyncio
import sys
from decimal import Decimal
from pathlib import Path

import pandas as pd
from sqlalchemy import text

from app.config import get_settings
from app.database import async_session_factory
from app.ingestion.excel_inventory import (
    INVENTORY_WORKBOOK_FILENAME, ingest_inventory,
)

results: list[tuple[str, str, object]] = []


def check(name, condition, got=None):
    status = "PASS" if condition else "FAIL"
    results.append((name, status, got))
    print(f"{status}  {name}" + ("" if got is None else f"  (got: {got})"))


async def fetch_count(session, table: str) -> int:
    return (await session.execute(text(f"SELECT count(*) FROM {table}"))).scalar()


async def fetch_one(session, sql: str, **kw):
    return (await session.execute(text(sql), kw)).mappings().first()


async def main() -> int:
    # --- GROUP A: workbook + Phase 6 baseline ---
    path = Path(get_settings().data_dir) / INVENTORY_WORKBOOK_FILENAME
    if not path.exists():
        check("inventory workbook present", False, str(path))
        return 1
    check("inventory workbook present", True, path.name)

    xls = pd.ExcelFile(path)

    async with async_session_factory() as session:
        menu_items = await fetch_count(session, "menu_items")
        categories = await fetch_count(session, "categories")
    check("Phase 6 baseline: menu_items == 118", menu_items == 118, menu_items)
    check("Phase 6 baseline: categories == 8", categories == 8, categories)

    # --- GROUP B: ingest pass 1 + exact source-vs-DB counts ---
    async with async_session_factory() as session:
        await ingest_inventory(session)
        await session.commit()

    source_counts = {
        "suppliers": len(pd.read_excel(xls, "Suppliers")),
        "ingredients": len(pd.read_excel(xls, "Ingredients")),
        "branches": len(pd.read_excel(xls, "Branches")),
        "branch_stock": len(pd.read_excel(xls, "Branch_Stock")),
        "recipes": len(pd.read_excel(xls, "Recipes")),
        "stock_movements": len(pd.read_excel(xls, "Stock_Movements")),
    }

    async with async_session_factory() as session:
        pass1_counts = {}
        for table, exp in source_counts.items():
            got = await fetch_count(session, table)
            pass1_counts[table] = got
            check(f"{table}: source={exp} db={got}", exp == got, got)

        # --- GROUP C: Phase 6 placeholders gone ---
        zero_tables = (await session.execute(text(
            "SELECT count(*) FROM branches WHERE tables_count = 0"
        ))).scalar()
        check("NO placeholder branches remain", zero_tables == 0, zero_tables)

        placeholder_status = (await session.execute(text(
            "SELECT count(*) FROM ingredients WHERE status = 'Placeholder'"
        ))).scalar()
        check("NO placeholder ingredients remain", placeholder_status == 0, placeholder_status)

        non_active = (await session.execute(text(
            "SELECT count(*) FROM ingredients WHERE status <> 'Active'"
        ))).scalar()
        check("all ingredients are Active", non_active == 0, non_active)

        # --- GROUP D: computed fields populated + mathematically correct ---
        null_computed = (await session.execute(text(
            "SELECT count(*) FROM branch_stock WHERE on_hand IS NULL "
            "OR available IS NULL OR suggested_buy IS NULL "
            "OR stock_status IS NULL OR stock_value_pkr IS NULL"
        ))).scalar()
        check("no NULLs in branch_stock computed fields", null_computed == 0, null_computed)

        stock_rows = (await session.execute(text(
            "SELECT branch_id, ingredient_id, opening, received, consumed, wastage, "
            "adjustment, reserved, reorder_level, on_hand, available, stock_status "
            "FROM branch_stock"
        ))).mappings().all()

        mismatches = 0
        for row in stock_rows:
            exp_on_hand = (
                row["opening"] + row["received"] - row["consumed"]
                - row["wastage"] + row["adjustment"]
            )
            exp_available = max(0.0, exp_on_hand - row["reserved"])
            if exp_on_hand < 0:
                exp_status = "DATA ERROR"
            elif exp_available <= 0:
                exp_status = "OUT OF STOCK"
            elif exp_on_hand <= row["reorder_level"]:
                exp_status = "REORDER"
            else:
                exp_status = "OK"
            if (
                abs(row["on_hand"] - exp_on_hand) >= 1e-6
                or abs(row["available"] - exp_available) >= 1e-6
                or row["stock_status"] != exp_status
            ):
                mismatches += 1
        check(
            f"on_hand/available/status recompute matches DB ({len(stock_rows)} rows)",
            mismatches == 0,
            mismatches,
        )

        # --- GROUP E: no workbook-formula leakage in recipes ---
        leaked = (await session.execute(text(
            "SELECT count(*) FROM recipes WHERE qty_per_portion > 5.0"
        ))).scalar()
        check("recipes qty_per_portion > 5.0 count == 0", leaked == 0, leaked)

        bad_qty = (await session.execute(text(
            "SELECT count(*) FROM recipes WHERE qty_per_portion IS NULL "
            "OR qty_per_portion <= 0"
        ))).scalar()
        check("recipes qty_per_portion NULL/<=0 count == 0", bad_qty == 0, bad_qty)

        # --- GROUP F: stock_movements integrity ---
        mv_count = await fetch_count(session, "stock_movements")
        check(
            f"stock_movements count == source {source_counts['stock_movements']}",
            mv_count == source_counts["stock_movements"],
            mv_count,
        )
        null_dates = (await session.execute(text(
            "SELECT count(*) FROM stock_movements WHERE movement_date IS NULL"
        ))).scalar()
        check("no NULL movement_date", null_dates == 0, null_dates)

        types = set((await session.execute(text(
            "SELECT DISTINCT movement_type FROM stock_movements"
        ))).scalars().all())
        allowed = {
            "RECEIPT", "CONSUMPTION", "WASTAGE", "ADJUSTMENT", "RESERVATION",
        }
        check("movement types are valid", types <= allowed, sorted(types))

        row = await fetch_one(
            session,
            "SELECT qty_signed, movement_type FROM stock_movements "
            "WHERE movement_id = 'MOV0002'",
        )
        check(
            "MOV0002 qty_signed == -8.0",
            row and float(row["qty_signed"]) == -8.0,
            row and row["qty_signed"],
        )
        check(
            "MOV0002 movement_type == 'CONSUMPTION'",
            row and row["movement_type"] == "CONSUMPTION",
            row and row["movement_type"],
        )

        # --- GROUP G: spot rows ---
        row = await fetch_one(
            session,
            "SELECT unit_cost_pkr FROM ingredients WHERE ingredient_id = 'ING001'",
        )
        check(
            "ING001 unit_cost_pkr == 1100.00",
            row and row["unit_cost_pkr"] == Decimal("1100.00"),
            row and row["unit_cost_pkr"],
        )

        row = await fetch_one(
            session,
            "SELECT unit_cost_pkr FROM ingredients WHERE ingredient_id = 'ING004'",
        )
        check(
            "ING004 unit_cost_pkr == 2600.00",
            row and row["unit_cost_pkr"] == Decimal("2600.00"),
            row and row["unit_cost_pkr"],
        )

        row = await fetch_one(
            session,
            "SELECT ingredient_name FROM ingredients WHERE ingredient_id = 'ING060'",
        )
        check(
            "ING060 ingredient_name == 'Biryani masala'",
            row and row["ingredient_name"] == "Biryani masala",
            row and row["ingredient_name"],
        )

        row = await fetch_one(
            session,
            "SELECT supplier_name FROM suppliers WHERE supplier_id = 'SUP01'",
        )
        check(
            "SUP01 supplier_name == 'Karachi Protein Supply'",
            row and row["supplier_name"] == "Karachi Protein Supply",
            row and row["supplier_name"],
        )

        row = await fetch_one(
            session,
            "SELECT tables_count, seats, hours FROM branches "
            "WHERE branch_id = 'UTG-KHI-001'",
        )
        check(
            "UTG-KHI-001 tables_count == 18",
            row and row["tables_count"] == 18,
            row and row["tables_count"],
        )
        check(
            "UTG-KHI-001 seats == 72",
            row and row["seats"] == 72,
            row and row["seats"],
        )
        check(
            "UTG-KHI-001 hours == '24/7'",
            row and row["hours"] == "24/7",
            row and row["hours"],
        )

        row = await fetch_one(
            session,
            "SELECT tables_count, seats, hours FROM branches "
            "WHERE branch_id = 'UTG-KHI-002'",
        )
        check(
            "UTG-KHI-002 tables_count == 24",
            row and row["tables_count"] == 24,
            row and row["tables_count"],
        )
        check(
            "UTG-KHI-002 seats == 112",
            row and row["seats"] == 112,
            row and row["seats"],
        )
        check(
            "UTG-KHI-002 hours == '24/7'",
            row and row["hours"] == "24/7",
            row and row["hours"],
        )

        row = await fetch_one(
            session,
            "SELECT qty_per_portion FROM recipes "
            "WHERE menu_id = 'MENU001' AND ingredient_id = 'ING002'",
        )
        check(
            "Recipe (MENU001, ING002) qty_per_portion ≈ 0.25",
            row and abs(row["qty_per_portion"] - 0.25) < 1e-6,
            row and row["qty_per_portion"],
        )

        row = await fetch_one(
            session,
            "SELECT qty_per_portion FROM recipes "
            "WHERE menu_id = 'MENU011' AND ingredient_id = 'ING011'",
        )
        check(
            "Recipe (MENU011, ING011) qty_per_portion ≈ 1.0",
            row and abs(row["qty_per_portion"] - 1.0) < 1e-6,
            row and row["qty_per_portion"],
        )

        # The brief says 131, but the workbook itself contains 130 recipe rows
        # with zero duplicate (Menu_ID, Ingredient_ID) pairs. Group B already
        # requires source == DB, so asserting 131 would require fabricating a
        # recipe. Assert against the actual source count instead.
        recipe_count = await fetch_count(session, "recipes")
        check(
            f"Recipe count == {source_counts['recipes']} (source rows)",
            recipe_count == source_counts["recipes"],
            recipe_count,
        )

        row = await fetch_one(
            session,
            "SELECT on_hand, available, stock_status FROM branch_stock "
            "WHERE branch_id = 'UTG-KHI-001' AND ingredient_id = 'ING001'",
        )
        check(
            "BranchStock (UTG-KHI-001, ING001) on_hand ≈ 42.69",
            row and abs(row["on_hand"] - 42.69) < 1e-6,
            row and row["on_hand"],
        )
        check(
            "BranchStock (UTG-KHI-001, ING001) available ≈ 40.57",
            row and abs(row["available"] - 40.57) < 1e-6,
            row and row["available"],
        )
        check(
            "BranchStock (UTG-KHI-001, ING001) status == 'OK'",
            row and row["stock_status"] == "OK",
            row and row["stock_status"],
        )

        row = await fetch_one(
            session,
            "SELECT on_hand, available, stock_status FROM branch_stock "
            "WHERE branch_id = 'UTG-KHI-002' AND ingredient_id = 'ING017'",
        )
        check(
            "BranchStock (UTG-KHI-002, ING017) on_hand ≈ 0.99",
            row and abs(row["on_hand"] - 0.99) < 1e-6,
            row and row["on_hand"],
        )
        check(
            "BranchStock (UTG-KHI-002, ING017) available ≈ 0.94",
            row and abs(row["available"] - 0.94) < 1e-6,
            row and row["available"],
        )
        check(
            "BranchStock (UTG-KHI-002, ING017) status == 'REORDER'",
            row and row["stock_status"] == "REORDER",
            row and row["stock_status"],
        )

    # --- GROUP H: idempotency (pass 2) ---
    async with async_session_factory() as session:
        await ingest_inventory(session)
        await session.commit()

    async with async_session_factory() as session:
        for table, exp in pass1_counts.items():
            got = await fetch_count(session, table)
            check(f"idempotent re-run: {table} still {exp}", got == exp, got)

        zero_tables = (await session.execute(text(
            "SELECT count(*) FROM branches WHERE tables_count = 0"
        ))).scalar()
        check("idempotent: NO placeholder branches", zero_tables == 0, zero_tables)

        placeholder_status = (await session.execute(text(
            "SELECT count(*) FROM ingredients WHERE status = 'Placeholder'"
        ))).scalar()
        check("idempotent: NO placeholder ingredients", placeholder_status == 0, placeholder_status)

    print()
    print("=" * 60)
    failed = [r for r in results if r[1] == "FAIL"]
    print(f"PHASE 7 SELF-CHECK — {len(results) - len(failed)}/{len(results)} passed")
    print("=" * 60)
    if failed:
        print("FAILED CHECKS:")
        for name, _, got in failed:
            print(f"  - {name}  (got: {got})")
        print()
        return 1
    print("INVENTORY INGESTION VERIFIED: exact counts, computed stock, idempotent.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
