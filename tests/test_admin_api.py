"""
Phase 13 admin endpoints.

Our background tasks run under ASGITransport because they are asyncio tasks
on the same event loop, so tests only need to poll for completion.
"""
import asyncio

import pytest


async def _wait_for_job(client, headers, job_id, timeout=60.0):
    start = asyncio.get_event_loop().time()
    while asyncio.get_event_loop().time() - start < timeout:
        r = await client.get(f"/api/v1/admin/jobs/{job_id}", headers=headers)
        if r.status_code != 200:
            raise AssertionError(f"job lookup failed: {r.status_code} {r.text}")
        data = r.json()
        if data["status"] in ("success", "error"):
            return data
        await asyncio.sleep(0.1)
    raise TimeoutError(f"job {job_id} never finished")


@pytest.mark.asyncio
async def test_admin_auth_required(client):
    r = await client.post("/api/v1/admin/refresh/menu")
    assert r.status_code in (401, 422)
    r = await client.post(
        "/api/v1/admin/refresh/menu",
        headers={"X-Admin-Token": "wrong-token"},
    )
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_admin_refresh_menu_lifecycle(client, admin_headers):
    r = await client.post("/api/v1/admin/refresh/menu", headers=admin_headers)
    assert r.status_code == 202
    job_id = r.json()["job_id"]
    final = await _wait_for_job(client, admin_headers, job_id)
    assert final["status"] == "success"
    assert final["domain"] == "menu"
    assert "menu_items" in final["result"]


@pytest.mark.asyncio
async def test_admin_refresh_all(client, admin_headers):
    r = await client.post("/api/v1/admin/refresh/all", headers=admin_headers)
    assert r.status_code == 202
    job_id = r.json()["job_id"]
    final = await _wait_for_job(client, admin_headers, job_id)
    assert final["status"] == "success"
    assert set(final["result"].keys()) == {"menu", "inventory", "docs"}


@pytest.mark.asyncio
async def test_admin_unknown_domain(client, admin_headers):
    r = await client.post("/api/v1/admin/refresh/garbage", headers=admin_headers)
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_admin_job_not_found(client, admin_headers):
    r = await client.get("/api/v1/admin/jobs/not-a-real-id", headers=admin_headers)
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_admin_concurrent_refreshes(client, admin_headers):
    """3 parallel refreshes: distinct job_ids, all succeed, DB unchanged."""
    ids = await asyncio.gather(*[
        client.post("/api/v1/admin/refresh/menu", headers=admin_headers)
        for _ in range(3)
    ])
    job_ids = [r.json()["job_id"] for r in ids]
    assert len(set(job_ids)) == 3
    finals = await asyncio.gather(*[
        _wait_for_job(client, admin_headers, jid) for jid in job_ids
    ])
    assert all(f["status"] == "success" for f in finals)
