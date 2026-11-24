"""
Phase 11 menu endpoints.
"""
import pytest


@pytest.mark.asyncio
async def test_categories(client):
    r = await client.get("/api/v1/menu/categories")
    assert r.status_code == 200
    cats = r.json()
    assert len(cats) == 8
    ids = {c["category_id"] for c in cats}
    assert ids == {"CAT-PK", "CAT-BBQ", "CAT-FF", "CAT-PIZ",
                   "CAT-CH", "CAT-BR", "CAT-DS", "CAT-BV"}


@pytest.mark.asyncio
async def test_menu_items_default_active(client):
    r = await client.get("/api/v1/menu/items")
    assert r.status_code == 200
    items = r.json()
    assert len(items) == 32
    for it in items:
        assert it["catalog_status"] == "Active"


@pytest.mark.asyncio
async def test_menu_items_all(client):
    r = await client.get("/api/v1/menu/items?catalog_status=all")
    assert r.status_code == 200
    assert len(r.json()) == 118


@pytest.mark.asyncio
async def test_menu_items_category_filter(client):
    r = await client.get("/api/v1/menu/items?category=BBQ")
    items = r.json()
    # Default catalog_status is Active, so only the 4 active BBQ items.
    assert len(items) == 4
    assert all(i["category"] == "BBQ" for i in items)


@pytest.mark.asyncio
async def test_menu_items_search(client):
    r = await client.get("/api/v1/menu/items?q=karahi&catalog_status=all")
    items = r.json()
    assert len(items) == 5
    ids = {i["menu_id"] for i in items}
    assert ids == {"MENU003", "MENU004", "MENU035", "MENU036", "MENU037"}


@pytest.mark.asyncio
async def test_menu_item_detail(client):
    r = await client.get("/api/v1/menu/items/MENU001")
    assert r.status_code == 200
    body = r.json()
    assert body["item_name"] == "Chicken Biryani"
    assert body["base_price_pkr"] == 420.0
    assert len(body["variants"]) == 1
    assert body["variants"][0]["variant_id"] == "VAR-MENU001-STD"


@pytest.mark.asyncio
async def test_menu_item_404(client):
    r = await client.get("/api/v1/menu/items/MENU999")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_variants_ordering(client):
    r = await client.get("/api/v1/menu/items/MENU003/variants")
    assert r.status_code == 200
    variants = r.json()
    assert len(variants) == 2
    # Ordered by price ASC
    assert variants[0]["price_pkr"] < variants[1]["price_pkr"]
    full = [v for v in variants if v["variant_id"] == "VAR-MENU003-FULL"][0]
    assert full["approved_for_orders"] is False


@pytest.mark.asyncio
async def test_addons(client):
    r = await client.get("/api/v1/menu/items/MENU001/addons")
    assert r.status_code == 200
    addons = r.json()
    ids = {a["addon_id"] for a in addons}
    assert "ADD006" in ids  # Extra Naan
    assert "ADD003" in ids  # Extra Chicken


@pytest.mark.asyncio
async def test_addons_non_selectable(client):
    r = await client.get("/api/v1/menu/items/MENU011/addons")
    addons = r.json()
    drink = [a for a in addons if a["addon_id"] == "ADD010"][0]
    assert drink["selectable"] is False


@pytest.mark.asyncio
async def test_aliases(client):
    r = await client.get("/api/v1/menu/aliases?phrase=chai")
    assert r.status_code == 200
    results = r.json()
    assert len(results) >= 1
    assert any(a["menu_id"] == "MENU030" and a["language"] == "Roman Urdu"
               for a in results)


@pytest.mark.asyncio
async def test_aliases_no_match(client):
    r = await client.get("/api/v1/menu/aliases?phrase=XYZ_NOT_FOUND")
    assert r.status_code == 200
    assert r.json() == []


@pytest.mark.asyncio
async def test_aliases_missing_param(client):
    r = await client.get("/api/v1/menu/aliases")
    assert r.status_code == 422
