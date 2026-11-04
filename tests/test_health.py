"""
Phase 10 verification, now as permanent tests.
"""
import pytest


@pytest.mark.asyncio
async def test_health_top_level(client):
    r = await client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] in {"ok", "degraded"}
    assert body["db"] in {"ok", "down"}
    assert "version" in body


@pytest.mark.asyncio
async def test_health_has_request_id(client):
    r = await client.get("/health")
    rid = r.headers.get("X-Request-ID")
    assert rid is not None
    # Should parse as UUID4 OR be an opaque client-supplied ID
    assert len(rid) >= 8


@pytest.mark.asyncio
async def test_health_request_id_passthrough(client):
    r = await client.get("/health", headers={"X-Request-ID": "test-fixed-123"})
    assert r.headers["X-Request-ID"] == "test-fixed-123"


@pytest.mark.asyncio
async def test_api_v1_root(client):
    r = await client.get("/api/v1/")
    assert r.status_code == 200
    body = r.json()
    assert body["endpoints"]["health_top"] == "/health"
    for key in ["menu_items", "inventory_branches",
                "search_semantic_post", "admin_refresh"]:
        assert key in body["endpoints"], f"missing {key}"


@pytest.mark.asyncio
async def test_openapi_available(client):
    r = await client.get("/openapi.json")
    assert r.status_code == 200
    spec = r.json()
    assert "Urban Tandoor" in spec["info"]["title"]
    paths = spec["paths"]
    for required in ["/health", "/api/v1/menu/items",
                     "/api/v1/inventory/branches",
                     "/api/v1/search/semantic",
                     "/api/v1/admin/refresh/{domain}"]:
        assert required in paths, f"missing {required}"
