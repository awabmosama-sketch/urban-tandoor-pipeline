"""
Self-check for Phase 6. Run: python -m uv run python scripts/_selfcheck_6.py
Exits 0 on success, 1 on failure.

Strategy: reads workbook rows = expected count. Queries DB = actual count.
Asserts equality (not "approx", not "at least"). Idempotency: re-runs ingest,
re-queries, asserts unchanged. Spot-rows: reads known cell values directly
from the workbook and compares to DB row.
"""
import asyncio
import sys
from decimal import Decimal
from pathlib import Path

import pandas as pd
from sqlalchemy import text

from app.config import get_settings
from app.database import async_session_factory
from app.ingestion.excel_menu import (
    MENU_WORKBOOK_FILENAME, ingest_menu_catalog,
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
    path = Path(get_settings().data_dir) / MENU_WORKBOOK_FILENAME
    if not path.exists():
        check("workbook present", False, str(path))
        return 1
    check("workbook present", True, path.name)

    xls = pd.ExcelFile(path)
    expected = {
        "categories":     len(pd.read_excel(xls, "Categories")),
        "menu_items":     len(pd.read_excel(xls, "Menu_Items")),
        "variants":       len(pd.read_excel(xls, "Variants")),
        "addons":         len(pd.read_excel(xls, "Addons")),
        "item_addons":    len(pd.read_excel(xls, "Item_Addons")),
        "item_aliases":   len(pd.read_excel(xls, "Item_Aliases")),
        "branch_menu":    len(pd.read_excel(xls, "Branch_Menu")),
        "inventory_links":len(pd.read_excel(xls, "Inventory_Links")),
        "deals":          len(pd.read_excel(xls, "Deals")),
        "deal_items":     len(pd.read_excel(xls, "Deal_Items")),
        "allergen_guide": len(pd.read_excel(xls, "Allergen_Guide")),
        "service_rules":  len(pd.read_excel(xls, "Service_Rules")),
    }

    # --- RUN INGEST (pass 1) ---
    async with async_session_factory() as session:
        pass1 = await ingest_menu_catalog(session)
        await session.commit()

    # --- VERIFY EXACT COUNTS ---
    async with async_session_factory() as session:
        for table, exp in expected.items():
            got = await fetch_count(session, table)
            check(f"{table}: source={exp} db={got}", exp == got, got)

    # --- SPOT ROWS ---
    async with async_session_factory() as session:
        row = await fetch_one(
            session,
            "SELECT item_name, category, base_price_pkr, prep_time_min, "
            "recipe_linked, catalog_status, dietary_hint "
            "FROM menu_items WHERE menu_id = 'MENU001'",
        )
        check("MENU001 item_name == Chicken Biryani",
              row and row["item_name"] == "Chicken Biryani", row and row["item_name"])
        check("MENU001 base_price_pkr == 420.00",
              row and row["base_price_pkr"] == Decimal("420.00"), row and row["base_price_pkr"])
        check("MENU001 prep_time_min == 35",
              row and row["prep_time_min"] == 35, row and row["prep_time_min"])
        check("MENU001 recipe_linked is True",
              row and row["recipe_linked"] is True, row and row["recipe_linked"])
        check("MENU001 dietary_hint == 'Non-Vegetarian'",
              row and row["dietary_hint"] == "Non-Vegetarian", row and row["dietary_hint"])

        row = await fetch_one(
            session,
            "SELECT catalog_status, recipe_linked FROM menu_items "
            "WHERE menu_id = 'MENU033'",
        )
        check("MENU033 catalog_status == 'Draft - Recipe Needed'",
              row and row["catalog_status"] == "Draft - Recipe Needed",
              row and row["catalog_status"])
        check("MENU033 recipe_linked is False",
              row and row["recipe_linked"] is False, row and row["recipe_linked"])

        row = await fetch_one(
            session,
            "SELECT service_window FROM menu_items WHERE menu_id = 'MENU023'",
        )
        check("MENU023 service_window == '06:00–12:00 (demo)'",
              row and row["service_window"] == "06:00–12:00 (demo)",
              row and row["service_window"])

        row = await fetch_one(
            session,
            "SELECT price_pkr, approved_for_orders FROM variants "
            "WHERE variant_id = 'VAR-MENU003-FULL'",
        )
        check("VAR-MENU003-FULL price_pkr == 3150.00",
              row and row["price_pkr"] == Decimal("3150.00"), row and row["price_pkr"])
        check("VAR-MENU003-FULL approved_for_orders is False",
              row and row["approved_for_orders"] is False,
              row and row["approved_for_orders"])

        row = await fetch_one(
            session,
            "SELECT customer_phrase, language FROM item_aliases "
            "WHERE alias_id = 'ALS0044'",
        )
        check("ALS0044 phrase == 'chai'", row and row["customer_phrase"] == "chai",
              row and row["customer_phrase"])
        check("ALS0044 language == 'Roman Urdu'",
              row and row["language"] == "Roman Urdu", row and row["language"])

        row = await fetch_one(
            session,
            "SELECT deal_price_pkr, approval_status, min_spend_pkr, stack_bank_discount "
            "FROM deals WHERE deal_id = 'DEAL002'",
        )
        check("DEAL002 deal_price_pkr == 1090.00",
              row and row["deal_price_pkr"] == Decimal("1090.00"),
              row and row["deal_price_pkr"])
        check("DEAL002 approval_status == 'Draft'",
              row and row["approval_status"] == "Draft", row and row["approval_status"])
        check("DEAL002 min_spend_pkr is None",
              row and row["min_spend_pkr"] is None, row and row["min_spend_pkr"])
        check("DEAL002 stack_bank_discount is False",
              row and row["stack_bank_discount"] is False,
              row and row["stack_bank_discount"])

        row = await fetch_one(
            session,
            "SELECT category_name, sort_order FROM categories "
            "WHERE category_id = 'CAT-BBQ'",
        )
        check("CAT-BBQ sort_order == 2", row and row["sort_order"] == 2,
              row and row["sort_order"])

        # No NULLs in critical columns
        nulls = (await session.execute(text(
            "SELECT count(*) FROM menu_items WHERE base_price_pkr IS NULL "
            "OR category_id IS NULL OR item_name IS NULL"
        ))).scalar()
        check("no NULL criticals in menu_items", nulls == 0, nulls)

        orphan_fk = (await session.execute(text(
            "SELECT count(*) FROM menu_items m "
            "LEFT JOIN categories c ON c.category_id = m.category_id "
            "WHERE c.category_id IS NULL"
        ))).scalar()
        check("no orphan category_id FKs in menu_items", orphan_fk == 0, orphan_fk)

    # --- IDEMPOTENCY: RUN INGEST (pass 2), VERIFY UNCHANGED ---
    async with async_session_factory() as session:
        await ingest_menu_catalog(session)
        await session.commit()

    async with async_session_factory() as session:
        for table, exp in expected.items():
            got = await fetch_count(session, table)
            check(f"idempotent re-run: {table} still {exp}", got == exp, got)

    print()
    print("=" * 60)
    failed = [r for r in results if r[1] == "FAIL"]
    print(f"PHASE 6 SELF-CHECK  —  {len(results) - len(failed)}/{len(results)} passed")
    print("=" * 60)
    if failed:
        print("FAILED CHECKS:")
        for name, _, got in failed:
            print(f"  - {name}  (got: {got})")
        print()
        print("RESULT: NEEDS FIX")
        return 1
    print("MENU INGESTION VERIFIED: exact counts, spot rows, idempotent.")
    print("RESULT: READY FOR PHASE 7 (inventory ingestion)")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
