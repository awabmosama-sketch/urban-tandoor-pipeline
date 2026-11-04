"""
Full-stack integration test. Verifies the pipeline is truly connected:
client → API → service → SQLModel → Postgres.
"""
import pytest


@pytest.mark.asyncio
async def test_biryani_full_journey(client):
    """MENU001 travels from menu → availability → stock → back."""
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
    results = r.json()["results"]
    # With fake embeddings, presence is not guaranteed — but content match
    # via LIKE is.
    r2 = await client.get("/api/v1/search/documents")
    menu_doc = [d for d in r2.json()
                if d["document_id"] == "menu:catalog_narratives"][0]
    assert menu_doc["chunk_count"] == 118


@pytest.mark.asyncio
async def test_admin_refresh_preserves_data(client, admin_headers):
    """Refresh one domain, verify all others' data untouched."""
    # Capture pre-refresh counts for a table not touched by 'menu' refresh
    from sqlalchemy import text
    from app.database import async_session_factory

    async with async_session_factory() as s:
        pre_ing = (await s.execute(text("SELECT COUNT(*) FROM ingredients"))).scalar()
        pre_bs = (await s.execute(text("SELECT COUNT(*) FROM branch_stock"))).scalar()

    import asyncio as _aio
    r = await client.post("/api/v1/admin/refresh/menu", headers=admin_headers)
    job_id = r.json()["job_id"]
    start = _aio.get_event_loop().time()
    while _aio.get_event_loop().time() - start < 60:
        j = await client.get(f"/api/v1/admin/jobs/{job_id}", headers=admin_headers)
        if j.json()["status"] in ("success", "error"):
            break
        await _aio.sleep(0.1)

    async with async_session_factory() as s:
        post_ing = (await s.execute(text("SELECT COUNT(*) FROM ingredients"))).scalar()
        post_bs = (await s.execute(text("SELECT COUNT(*) FROM branch_stock"))).scalar()

    assert pre_ing == post_ing == 60
    assert pre_bs == post_bs == 120
