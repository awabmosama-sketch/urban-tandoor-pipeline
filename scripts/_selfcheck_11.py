"""
Self-check for Phase 11 (menu + inventory read APIs).

Run: python -m uv run python scripts/_selfcheck_11.py
Exits 0 on success, 1 on failure.

Exercises the real HTTP layer via httpx.ASGITransport and cross-verifies
selected results against the database with read-only SELECTs.
"""
from __future__ import annotations

import asyncio
import re
import subprocess
import sys
from pathlib import Path

import httpx
from sqlalchemy import text

from app.database import async_session_factory, engine
from app.main import app

ROOT = Path(__file__).resolve().parents[1]

TABLES = [
    "suppliers", "ingredients", "branches", "branch_stock", "recipes",
    "stock_movements", "categories", "menu_items", "variants", "addons",
    "item_addons", "item_aliases", "branch_menu", "inventory_links",
    "deals", "deal_items", "allergen_guide", "service_rules",
    "source_documents", "document_chunks",
]

CATEGORY_IDS = {"CAT-PK", "CAT-BBQ", "CAT-FF", "CAT-PIZ", "CAT-CH", "CAT-BR", "CAT-DS", "CAT-BV"}

NEW_PATHS = {
    "/api/v1/menu/categories",
    "/api/v1/menu/items",
    "/api/v1/menu/items/{menu_id}",
    "/api/v1/menu/items/{menu_id}/variants",
    "/api/v1/menu/items/{menu_id}/addons",
    "/api/v1/menu/aliases",
    "/api/v1/inventory/branches",
    "/api/v1/inventory/branches/{branch_id}/stock",
    "/api/v1/inventory/branches/{branch_id}/stock/{ingredient_id}",
    "/api/v1/inventory/availability/{menu_id}",
    "/api/v1/inventory/branches/{branch_id}/availability",
}

API_ENDPOINT_KEYS = {
    "health_top", "health_v1", "menu_categories", "menu_items",
    "menu_item_detail", "menu_item_variants", "menu_item_addons",
    "menu_aliases", "inventory_branches", "inventory_stock",
    "inventory_stock_detail", "availability_single", "availability_bulk",
}

BRANCH_1 = "UTG-KHI-001"
BRANCH_2 = "UTG-KHI-002"

results: list[tuple[str, str, object]] = []


def check(name: str, condition: bool, got=None) -> None:
    status = "PASS" if condition else "FAIL"
    results.append((name, status, got))
    print(f"{status}  {name}" + ("" if got is None else f"  (got: {got})"))


def run_pytest() -> tuple[int, str]:
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-q"],
        capture_output=True, text=True, cwd=str(ROOT), timeout=600,
    )
    out = (proc.stdout or "") + (proc.stderr or "")
    m = re.search(r"(\d+) passed", out)
    passed = int(m.group(1)) if m else 0
    return passed, out.strip().splitlines()[-1] if out.strip() else ""


async def db_count(session, sql: str, **params) -> int:
    return int((await session.execute(text(sql), params)).scalar())


async def db_counts() -> dict[str, int]:
    async with async_session_factory() as session:
        return {t: await db_count(session, f"SELECT count(*) FROM {t}") for t in TABLES}


async def get(client: httpx.AsyncClient, path: str, **params):
    resp = await client.get(path, params=params or None)
    try:
        body = resp.json()
    except Exception:  # noqa: BLE001
        body = None
    return resp, body


async def checks(pytest_passed: int, pytest_tail: str) -> None:
    transport = httpx.ASGITransport(app=app)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            # --- GROUP A ---
            counts = await db_counts()
            check(
                "A1 DB baseline: all 20 tables non-zero",
                all(v > 0 for v in counts.values()),
                {t: v for t, v in counts.items() if v == 0} or "20/20 non-zero",
            )
            check(
                "A2 pytest passes with 2+ tests",
                pytest_passed >= 2 and "failed" not in pytest_tail,
                pytest_tail,
            )

            # --- GROUP B: categories ---
            r, cats = await get(client, "/api/v1/menu/categories")
            check("B1 categories 200 + length 8", r.status_code == 200 and len(cats or []) == 8, (r.status_code, len(cats or [])))
            cat_ids = {c["category_id"] for c in cats or []}
            check("B2 all 8 category_ids present", cat_ids == CATEGORY_IDS, sorted(cat_ids))
            bbq = next((c for c in cats or [] if c["category_id"] == "CAT-BBQ"), {})
            check(
                "B3 CAT-BBQ sort_order=2, name='BBQ'",
                bbq.get("sort_order") == 2 and bbq.get("category_name") == "BBQ",
                (bbq.get("sort_order"), bbq.get("category_name")),
            )

            # --- GROUP C: menu list ---
            r, items = await get(client, "/api/v1/menu/items")
            check("C1 default Active items == 32", r.status_code == 200 and len(items or []) == 32, (r.status_code, len(items or [])))
            r, items_all = await get(client, "/api/v1/menu/items", catalog_status="all")
            check("C2 catalog_status=all == 118", r.status_code == 200 and len(items_all or []) == 118, len(items_all or []))
            r, drafts = await get(client, "/api/v1/menu/items", catalog_status="Draft - Recipe Needed")
            check("C3 Draft - Recipe Needed == 86", r.status_code == 200 and len(drafts or []) == 86, len(drafts or []))
            r, bbq_active = await get(client, "/api/v1/menu/items", category="BBQ")
            check(
                "C4 category=BBQ (default Active) == 4",
                r.status_code == 200 and len(bbq_active or []) == 4,
                len(bbq_active or []),
            )
            r, bbq_all = await get(client, "/api/v1/menu/items", category="BBQ", catalog_status="all")
            check(
                "C4b category=BBQ (all statuses) == 14",
                r.status_code == 200 and len(bbq_all or []) == 14,
                len(bbq_all or []),
            )
            r, bbq_active2 = await get(client, "/api/v1/menu/items", category="BBQ", catalog_status="Active")
            check(
                "C5 category=BBQ&catalog_status=Active == 4",
                r.status_code == 200 and len(bbq_active2 or []) == 4,
                len(bbq_active2 or []),
            )
            r, pk_active = await get(client, "/api/v1/menu/items", category="Pakistani")
            check(
                "C6 category=Pakistani (default Active) == 6",
                r.status_code == 200 and len(pk_active or []) == 6,
                len(pk_active or []),
            )
            r, pk_all = await get(client, "/api/v1/menu/items", category="Pakistani", catalog_status="all")
            check(
                "C6b category=Pakistani (all statuses) == 22",
                r.status_code == 200 and len(pk_all or []) == 22,
                len(pk_all or []),
            )
            r, karahi_active = await get(client, "/api/v1/menu/items", q="karahi")
            check(
                "C7 q=karahi (default Active) == 2",
                r.status_code == 200 and len(karahi_active or []) == 2,
                len(karahi_active or []),
            )
            r, karahi_all = await get(client, "/api/v1/menu/items", q="karahi", catalog_status="all")
            karahi_ids = {i["menu_id"] for i in karahi_all or []}
            check(
                "C7b q=karahi (all) == 5 expected IDs",
                r.status_code == 200
                and karahi_ids == {"MENU003", "MENU004", "MENU035", "MENU036", "MENU037"},
                sorted(karahi_ids),
            )
            _, page1 = await get(client, "/api/v1/menu/items", limit=5, offset=0)
            _, page2 = await get(client, "/api/v1/menu/items", limit=5, offset=5)
            check(
                "C8 pagination page1 != page2",
                [i["menu_id"] for i in page1 or []] != [i["menu_id"] for i in page2 or []],
                ([i["menu_id"] for i in page1 or []], [i["menu_id"] for i in page2 or []]),
            )
            required_fields = {
                "menu_id", "item_name", "category", "base_price_pkr",
                "catalog_status", "prep_time_min",
            }
            check(
                "C9 every item has required fields",
                bool(items) and all(required_fields <= set(i) for i in items),
                "all 32" if items else "no items",
            )
            _, biryani = await get(client, "/api/v1/menu/items", q="biryani")
            b1 = next((i for i in biryani or [] if i["menu_id"] == "MENU001"), {})
            check(
                "C10 MENU001 base_price_pkr == 420.0 (float)",
                b1.get("base_price_pkr") == 420.0 and isinstance(b1.get("base_price_pkr"), float),
                b1.get("base_price_pkr"),
            )

            # --- GROUP D: detail ---
            r, d1 = await get(client, "/api/v1/menu/items/MENU001")
            check(
                "D1 MENU001 detail correct",
                r.status_code == 200
                and d1.get("item_name") == "Chicken Biryani"
                and d1.get("base_price_pkr") == 420.0
                and d1.get("catalog_status") == "Active",
                (r.status_code, d1.get("item_name"), d1.get("base_price_pkr")),
            )
            v = (d1 or {}).get("variants") or []
            check(
                "D2 MENU001 has 1 variant VAR-MENU001-STD @420 approved",
                len(v) == 1 and v[0]["variant_id"] == "VAR-MENU001-STD"
                and v[0]["price_pkr"] == 420.0 and v[0]["approved_for_orders"] is True,
                v,
            )
            r, d3 = await get(client, "/api/v1/menu/items/MENU003")
            v3 = (d3 or {}).get("variants") or []
            check(
                "D3 MENU003 variants 2, price ASC, FULL not approved",
                r.status_code == 200
                and [x["variant_id"] for x in v3] == ["VAR-MENU003-STD", "VAR-MENU003-FULL"]
                and v3[0]["price_pkr"] == 1750.0 and v3[1]["price_pkr"] == 3150.0
                and v3[0]["approved_for_orders"] is True
                and v3[1]["approved_for_orders"] is False,
                v3,
            )
            r, _ = await get(client, "/api/v1/menu/items/MENU999")
            check("D4 MENU999 detail 404", r.status_code == 404, r.status_code)
            r, d5 = await get(client, "/api/v1/menu/items/MENU033")
            check(
                "D5 MENU033 catalog_status='Draft - Recipe Needed'",
                r.status_code == 200 and d5.get("catalog_status") == "Draft - Recipe Needed",
                (r.status_code, d5.get("catalog_status")),
            )
            check(
                "D6 MENU001 prep_time_min == 35",
                (d1 or {}).get("prep_time_min") == 35,
                (d1 or {}).get("prep_time_min"),
            )

            # --- GROUP E: variants/addons ---
            r, e1 = await get(client, "/api/v1/menu/items/MENU001/variants")
            check(
                "E1 MENU001 variants endpoint 1 element",
                r.status_code == 200 and len(e1 or []) == 1
                and e1[0]["variant_id"] == "VAR-MENU001-STD",
                (r.status_code, e1),
            )
            r, e2 = await get(client, "/api/v1/menu/items/MENU003/variants")
            check(
                "E2 MENU003 variants endpoint 2 elements (STD, FULL)",
                r.status_code == 200
                and [x["variant_id"] for x in e2 or []] == ["VAR-MENU003-STD", "VAR-MENU003-FULL"],
                e2,
            )
            r, _ = await get(client, "/api/v1/menu/items/MENU999/variants")
            check("E3 MENU999 variants 404", r.status_code == 404, r.status_code)
            r, e4 = await get(client, "/api/v1/menu/items/MENU001/addons")
            e4_ids = {a["addon_id"] for a in e4 or []}
            check(
                "E4 MENU001 addons include ADD006/ADD003, all selectable",
                r.status_code == 200 and e4_ids == {"ADD003", "ADD006"}
                and all(a["selectable"] is True for a in e4 or []),
                e4,
            )
            r, e5 = await get(client, "/api/v1/menu/items/MENU011/addons")
            e5_map = {a["addon_id"]: a for a in e5 or []}
            check(
                "E5 MENU011 includes ADD010 with selectable=False",
                r.status_code == 200 and e5_map.get("ADD010", {}).get("addon_name") == "Drink Upgrade"
                and e5_map.get("ADD010", {}).get("selectable") is False,
                e5_map.get("ADD010"),
            )
            r, _ = await get(client, "/api/v1/menu/items/MENU999/addons")
            check("E6 MENU999 addons 404", r.status_code == 404, r.status_code)
            async with async_session_factory() as session:
                db_addons = await db_count(
                    session,
                    "SELECT count(*) FROM item_addons WHERE menu_id = :m",
                    m="MENU001",
                )
            check(
                "E7 MENU001 addons == DB item_addons count",
                len(e4 or []) == db_addons,
                (len(e4 or []), db_addons),
            )

            # --- GROUP F: aliases ---
            r, f1 = await get(client, "/api/v1/menu/aliases", phrase="chai")
            chai = next(
                (a for a in f1 or []
                 if a["customer_phrase"].lower() == "chai" and a["menu_id"] == "MENU030"),
                None,
            )
            check(
                "F1 phrase=chai includes MENU030 'chai' (Roman Urdu)",
                r.status_code == 200 and chai is not None and chai["language"] == "Roman Urdu",
                (r.status_code, len(f1 or []), chai),
            )
            r, f2 = await get(client, "/api/v1/menu/aliases", phrase="biryani")
            check(
                "F2 phrase=biryani == 5, all contain biryani",
                r.status_code == 200 and len(f2 or []) == 5
                and all("biryani" in a["customer_phrase"].lower() for a in f2 or []),
                len(f2 or []),
            )
            r, f3 = await get(client, "/api/v1/menu/aliases", phrase="XYZ123")
            check("F3 phrase=XYZ123 -> 200 []", r.status_code == 200 and f3 == [], (r.status_code, f3))
            r, f4 = await get(client, "/api/v1/menu/aliases", phrase="chikkan")
            check(
                "F4 phrase=chikkan >= 5",
                r.status_code == 200 and len(f4 or []) >= 5,
                len(f4 or []),
            )
            r, _ = await get(client, "/api/v1/menu/aliases")
            check("F5 aliases without phrase -> 422", r.status_code == 422, r.status_code)

            # --- GROUP G: branches ---
            r, branches = await get(client, "/api/v1/inventory/branches")
            check("G1 branches == 2", r.status_code == 200 and len(branches or []) == 2, len(branches or []))
            bmap = {b["branch_id"]: b for b in branches or []}
            check(
                "G2 UTG-KHI-001 18 tables / 72 seats / 24-7",
                bmap.get(BRANCH_1, {}).get("tables_count") == 18
                and bmap.get(BRANCH_1, {}).get("seats") == 72
                and bmap.get(BRANCH_1, {}).get("hours") == "24/7",
                bmap.get(BRANCH_1),
            )
            check(
                "G3 UTG-KHI-002 24 tables / 112 seats / 24-7",
                bmap.get(BRANCH_2, {}).get("tables_count") == 24
                and bmap.get(BRANCH_2, {}).get("seats") == 112
                and bmap.get(BRANCH_2, {}).get("hours") == "24/7",
                bmap.get(BRANCH_2),
            )

            # --- GROUP H: stock ---
            r, stock = await get(client, f"/api/v1/inventory/branches/{BRANCH_1}/stock")
            check("H1 branch 1 stock == 60 rows", r.status_code == 200 and len(stock or []) == 60, len(stock or []))
            allowed = {"OK", "REORDER", "OUT OF STOCK", "DATA ERROR"}
            check(
                "H2 all stock_status values recognized",
                all(s["stock_status"] in allowed for s in stock or []),
                sorted({s["stock_status"] for s in stock or []}),
            )
            r, h3 = await get(client, f"/api/v1/inventory/branches/{BRANCH_1}/stock/ING001")
            check(
                "H3 ING001 branch1 available 40.57, OK",
                r.status_code == 200
                and abs(h3.get("available", 0) - 40.57) < 1e-6
                and h3.get("stock_status") == "OK",
                (r.status_code, h3.get("available"), h3.get("stock_status")),
            )
            r, h4 = await get(client, f"/api/v1/inventory/branches/{BRANCH_2}/stock/ING017")
            check(
                "H4 ING017 branch2 available 0.94, REORDER",
                r.status_code == 200
                and abs(h4.get("available", 0) - 0.94) < 1e-6
                and h4.get("stock_status") == "REORDER",
                (r.status_code, h4.get("available"), h4.get("stock_status")),
            )
            r, _ = await get(client, "/api/v1/inventory/branches/UTG-KHI-999/stock")
            check("H5 unknown branch stock 404", r.status_code == 404, r.status_code)
            r, _ = await get(client, f"/api/v1/inventory/branches/{BRANCH_1}/stock/ING999")
            check("H6 unknown ingredient stock 404", r.status_code == 404, r.status_code)

            # --- GROUP I: availability single ---
            r, i1 = await get(client, "/api/v1/inventory/availability/MENU001", branch_id=BRANCH_1)
            check(
                "I1 MENU001@001 max=142 AVAILABLE limit ING002",
                r.status_code == 200 and i1.get("max_portions") == 142
                and i1.get("status") == "AVAILABLE"
                and i1.get("limiting_ingredient_id") == "ING002",
                (i1.get("max_portions"), i1.get("status"), i1.get("limiting_ingredient_id")),
            )
            r, i2 = await get(client, "/api/v1/inventory/availability/MENU001", branch_id=BRANCH_2)
            check(
                "I2 MENU001@002 max=250 AVAILABLE",
                r.status_code == 200 and i2.get("max_portions") == 250 and i2.get("status") == "AVAILABLE",
                (i2.get("max_portions"), i2.get("status")),
            )
            r, i3 = await get(client, "/api/v1/inventory/availability/MENU004", branch_id=BRANCH_1)
            check(
                "I3 MENU004@001 max=6 AVAILABLE limit ING004",
                r.status_code == 200 and i3.get("max_portions") == 6
                and i3.get("status") == "AVAILABLE"
                and i3.get("limiting_ingredient_id") == "ING004",
                (i3.get("max_portions"), i3.get("status"), i3.get("limiting_ingredient_id")),
            )
            r, i4 = await get(client, "/api/v1/inventory/availability/MENU015", branch_id=BRANCH_1)
            check(
                "I4 MENU015@001 max=44 AVAILABLE",
                r.status_code == 200 and i4.get("max_portions") == 44 and i4.get("status") == "AVAILABLE",
                (i4.get("max_portions"), i4.get("status")),
            )
            r, i5 = await get(client, "/api/v1/inventory/availability/MENU015", branch_id=BRANCH_2)
            check(
                "I5 MENU015@002 max=5 AVAILABLE limit ING017",
                r.status_code == 200 and i5.get("max_portions") == 5
                and i5.get("status") == "AVAILABLE"
                and i5.get("limiting_ingredient_id") == "ING017",
                (i5.get("max_portions"), i5.get("status"), i5.get("limiting_ingredient_id")),
            )
            r, i6 = await get(client, "/api/v1/inventory/availability/MENU022", branch_id=BRANCH_2)
            check(
                "I6 MENU022@002 max=4 AVAILABLE",
                r.status_code == 200 and i6.get("max_portions") == 4 and i6.get("status") == "AVAILABLE",
                (i6.get("max_portions"), i6.get("status")),
            )
            r, i7 = await get(client, "/api/v1/inventory/availability/MENU033", branch_id=BRANCH_1)
            check(
                "I7 MENU033 draft -> NOT_ACTIVE, max=0",
                r.status_code == 200 and i7.get("max_portions") == 0
                and i7.get("status") == "NOT_ACTIVE"
                and i7.get("catalog_status") == "Draft - Recipe Needed",
                (i7.get("max_portions"), i7.get("status"), i7.get("catalog_status")),
            )
            r, _ = await get(client, "/api/v1/inventory/availability/MENU999", branch_id=BRANCH_1)
            check("I8 unknown menu availability 404", r.status_code == 404, r.status_code)
            r, _ = await get(client, "/api/v1/inventory/availability/MENU001", branch_id="UTG-KHI-999")
            check("I9 unknown branch availability 404", r.status_code == 404, r.status_code)
            r, _ = await get(client, "/api/v1/inventory/availability/MENU001")
            check("I10 availability without branch_id -> 422", r.status_code == 422, r.status_code)

            # --- GROUP J: availability bulk ---
            r, j1 = await get(client, f"/api/v1/inventory/branches/{BRANCH_1}/availability")
            j1_map = {x["menu_id"]: x for x in j1 or []}
            check("J1 branch1 bulk availability == 32", r.status_code == 200 and len(j1 or []) == 32, len(j1 or []))
            check("J2 bulk MENU001@001 max=142", j1_map.get("MENU001", {}).get("max_portions") == 142, j1_map.get("MENU001", {}).get("max_portions"))
            check("J3 bulk MENU004@001 max=6", j1_map.get("MENU004", {}).get("max_portions") == 6, j1_map.get("MENU004", {}).get("max_portions"))
            check("J4 bulk MENU015@001 max=44", j1_map.get("MENU015", {}).get("max_portions") == 44, j1_map.get("MENU015", {}).get("max_portions"))
            r, j5 = await get(client, f"/api/v1/inventory/branches/{BRANCH_2}/availability")
            j5_map = {x["menu_id"]: x for x in j5 or []}
            check("J5 branch2 bulk availability == 32", r.status_code == 200 and len(j5 or []) == 32, len(j5 or []))
            check("J6 bulk MENU001@002 max=250", j5_map.get("MENU001", {}).get("max_portions") == 250, j5_map.get("MENU001", {}).get("max_portions"))
            check("J7 bulk MENU015@002 max=5", j5_map.get("MENU015", {}).get("max_portions") == 5, j5_map.get("MENU015", {}).get("max_portions"))
            check("J8 bulk MENU022@002 max=4", j5_map.get("MENU022", {}).get("max_portions") == 4, j5_map.get("MENU022", {}).get("max_portions"))
            r, j9 = await get(client, f"/api/v1/inventory/branches/{BRANCH_1}/availability", category="BBQ")
            check(
                "J9 branch1 BBQ bulk == 4",
                r.status_code == 200 and len(j9 or []) == 4
                and all(x["catalog_status"] == "Active" for x in j9 or []),
                len(j9 or []),
            )
            r, _ = await get(client, "/api/v1/inventory/branches/UTG-KHI-999/availability")
            check("J10 unknown branch bulk 404", r.status_code == 404, r.status_code)

            # --- GROUP K: individual vs bulk cross-verify ---
            bulk = {BRANCH_1: j1_map, BRANCH_2: j5_map}
            for menu_id in ["MENU001", "MENU004", "MENU010", "MENU015", "MENU022"]:
                for branch_id in [BRANCH_1, BRANCH_2]:
                    r, single = await get(
                        client, f"/api/v1/inventory/availability/{menu_id}",
                        branch_id=branch_id,
                    )
                    b = bulk[branch_id].get(menu_id, {})
                    check(
                        f"K {menu_id}@{branch_id[-3:]} individual == bulk",
                        r.status_code == 200
                        and single.get("max_portions") == b.get("max_portions")
                        and single.get("status") == b.get("status"),
                        (single.get("max_portions"), b.get("max_portions"),
                         single.get("status"), b.get("status")),
                    )

            # --- GROUP L: OpenAPI ---
            r, spec = await get(client, "/openapi.json")
            check("L1 openapi 200", r.status_code == 200, r.status_code)
            paths = set((spec or {}).get("paths", {}))
            check(
                "L2 openapi contains all 11 menu/inventory paths",
                NEW_PATHS <= paths,
                sorted(NEW_PATHS - paths) or "all present",
            )
            item_params = {
                p.get("name")
                for p in (spec or {}).get("paths", {})
                .get("/api/v1/menu/items", {})
                .get("get", {})
                .get("parameters", [])
            }
            check(
                "L3 /menu/items exposes category,catalog_status,q,limit,offset",
                {"category", "catalog_status", "q", "limit", "offset"} <= item_params,
                sorted(item_params),
            )
            schemas = set((spec or {}).get("components", {}).get("schemas", {}))
            check(
                "L4 schemas include MenuItemOut/AvailabilityOut/BranchStockOut",
                {"MenuItemOut", "AvailabilityOut", "BranchStockOut"} <= schemas,
                sorted({"MenuItemOut", "AvailabilityOut", "BranchStockOut"} - schemas) or "all present",
            )

            # --- GROUP M: regression ---
            check(
                "M1 pytest: N passed, 0 failed, N >= 2",
                pytest_passed >= 2 and "failed" not in pytest_tail,
                pytest_tail,
            )
            r, health = await get(client, "/health")
            check(
                "M2 /health 200 with db=ok",
                r.status_code == 200 and health.get("db") == "ok",
                (r.status_code, health.get("db")),
            )
            r, root = await get(client, "/api/v1/")
            endpoints = (root or {}).get("endpoints") or {}
            check(
                "M3 /api/v1/ has all 13 endpoint keys",
                r.status_code == 200 and API_ENDPOINT_KEYS <= set(endpoints),
                sorted(API_ENDPOINT_KEYS - set(endpoints)) or "all present",
            )
    finally:
        await engine.dispose()


def main() -> int:
    pytest_passed, pytest_tail = run_pytest()
    asyncio.run(checks(pytest_passed, pytest_tail))

    print()
    print("=" * 60)
    failed = [r for r in results if r[1] == "FAIL"]
    print(f"PHASE 11 SELF-CHECK — {len(results) - len(failed)}/{len(results)} passed")
    print("=" * 60)
    if failed:
        print("FAILED CHECKS:")
        for name, _, got in failed:
            print(f"  - {name}  (got: {got})")
        print()
        return 1
    print("MENU + INVENTORY APIS VERIFIED: filters, detail, aliases, stock, availability.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
