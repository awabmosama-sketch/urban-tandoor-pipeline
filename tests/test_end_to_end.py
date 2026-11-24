"""
Full-stack integration test. Verifies the pipeline is truly connected:
client -> API -> service -> MongoDB, with data loaded from JSON snapshots.
"""
import asyncio

import pytest


@pytest.mark.asyncio
async def test_biryani_full_journey(client):
    """MENU001 travels from menu -> availability -> stock -> back."""
    # Menu
    r = await client.get("/api/v1/menu/items/MENU001")
    assert r.status_code == 200
    item = r.json()
    assert item["item_name"] == "Chicken Biryani"

    # Availability
    r = await client.get(
        "/api/v1/inventory/availability/MENU001?branch_id=UTG-KHI-001"
    )
    avail = r.json()
    assert avail["max_portions"] == 142

    # Underlying stock
    r = await client.get(
        "/api/v1/inventory/branches/UTG-KHI-001/stock/ING002"
    )
    stock = r.json()
    assert stock["available"] > 0

    # Alias lookup
    r = await client.get("/api/v1/menu/aliases?phrase=chicken+biryani")
    aliases = r.json()
    assert any(a["menu_id"] == "MENU001" for a in aliases)


@pytest.mark.asyncio
async def test_search_finds_menu_content(client):
    """A semantic search for menu content should hit menu narrative chunks."""
    r = await client.get("/api/v1/search/semantic?q=MENU001+Chicken+Biryani&k=20")
    assert r.status_code == 200
    r2 = await client.get("/api/v1/search/documents")
    menu_doc = [d for d in r2.json()
                if d["document_id"] == "menu:catalog_narratives"][0]
    assert menu_doc["chunk_count"] == 118


@pytest.mark.asyncio
async def test_admin_refresh_preserves_data(client, db, admin_headers):
    """Refresh one domain, verify all others' data untouched."""
    pre_ing = await db.ingredients.count_documents({})
    pre_bs = await db.branch_stock.count_documents({})

    r = await client.post("/api/v1/admin/refresh/menu", headers=admin_headers)
    job_id = r.json()["job_id"]
    start = asyncio.get_event_loop().time()
    while asyncio.get_event_loop().time() - start < 60:
        j = await client.get(f"/api/v1/admin/jobs/{job_id}", headers=admin_headers)
        if j.json()["status"] in ("success", "error"):
            break
        await asyncio.sleep(0.1)

    post_ing = await db.ingredients.count_documents({})
    post_bs = await db.branch_stock.count_documents({})

    assert pre_ing == post_ing == 60
    assert pre_bs == post_bs == 120
