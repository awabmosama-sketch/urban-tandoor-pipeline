"""
Phase 11 inventory endpoints.
"""
import pytest


@pytest.mark.asyncio
async def test_branches(client):
    r = await client.get("/api/v1/inventory/branches")
    assert r.status_code == 200
    branches = r.json()
    assert len(branches) == 2
    pechs = [b for b in branches if b["branch_id"] == "UTG-KHI-001"][0]
    assert pechs["tables_count"] == 18
    assert pechs["seats"] == 72
    assert pechs["hours"] == "24/7"


@pytest.mark.asyncio
async def test_branch_stock(client):
    r = await client.get("/api/v1/inventory/branches/UTG-KHI-001/stock")
    assert r.status_code == 200
    stock = r.json()
    assert len(stock) == 60
    for row in stock:
        assert row["stock_status"] in {"OK", "REORDER", "OUT OF STOCK", "DATA ERROR"}


@pytest.mark.asyncio
async def test_branch_stock_single(client):
    r = await client.get("/api/v1/inventory/branches/UTG-KHI-001/stock/ING001")
    assert r.status_code == 200
    row = r.json()
    assert abs(row["available"] - 40.57) < 1e-6
    assert row["stock_status"] == "OK"


@pytest.mark.asyncio
async def test_branch_stock_reorder_status(client):
    r = await client.get("/api/v1/inventory/branches/UTG-KHI-002/stock/ING017")
    assert r.status_code == 200
    row = r.json()
    assert abs(row["available"] - 0.94) < 1e-6
    assert row["stock_status"] == "REORDER"


@pytest.mark.asyncio
async def test_branch_stock_404_branch(client):
    r = await client.get("/api/v1/inventory/branches/UTG-KHI-999/stock")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_branch_stock_404_ingredient(client):
    r = await client.get("/api/v1/inventory/branches/UTG-KHI-001/stock/ING999")
    assert r.status_code == 404
