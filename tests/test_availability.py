"""
Phase 11 availability formula — THE DECISIVE TEST SUITE.
Expected values from workbook Snapshot_Max_Portions, verified by Phases 7 and 11.
"""
import pytest

EXPECTED = [
    # (menu_id, branch_id, expected_portions, expected_status, expected_limiting)
    ("MENU001", "UTG-KHI-001", 142, "AVAILABLE", "ING002"),
    ("MENU001", "UTG-KHI-002", 250, "AVAILABLE", None),
    ("MENU004", "UTG-KHI-001", 6, "AVAILABLE", "ING004"),
    ("MENU015", "UTG-KHI-001", 44, "AVAILABLE", None),
    ("MENU015", "UTG-KHI-002", 5, "AVAILABLE", "ING017"),
    ("MENU022", "UTG-KHI-002", 4, "AVAILABLE", None),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("menu_id,branch_id,expected_p,expected_s,expected_limit", EXPECTED)
async def test_availability_individual(
    client, menu_id, branch_id, expected_p, expected_s, expected_limit
):
    r = await client.get(
        f"/api/v1/inventory/availability/{menu_id}?branch_id={branch_id}"
    )
    assert r.status_code == 200
    body = r.json()
    assert body["max_portions"] == expected_p, \
        f"{menu_id}@{branch_id}: expected {expected_p}, got {body['max_portions']}"
    assert body["status"] == expected_s
    if expected_limit is not None:
        assert body["limiting_ingredient_id"] == expected_limit, (
            f"{menu_id}@{branch_id}: expected limiting={expected_limit}, "
            f"got {body.get('limiting_ingredient_id')}"
        )


@pytest.mark.asyncio
async def test_availability_draft_item(client):
    r = await client.get(
        "/api/v1/inventory/availability/MENU033?branch_id=UTG-KHI-001"
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "NOT_ACTIVE"
    assert body["max_portions"] == 0


@pytest.mark.asyncio
async def test_availability_404_menu(client):
    r = await client.get(
        "/api/v1/inventory/availability/MENU999?branch_id=UTG-KHI-001"
    )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_availability_404_branch(client):
    r = await client.get(
        "/api/v1/inventory/availability/MENU001?branch_id=UTG-KHI-999"
    )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_availability_missing_branch_param(client):
    r = await client.get("/api/v1/inventory/availability/MENU001")
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_bulk_availability_matches_individual(client):
    """Cross-verify bulk vs individual for 5 items × 2 branches."""
    for branch_id in ["UTG-KHI-001", "UTG-KHI-002"]:
        bulk_r = await client.get(
            f"/api/v1/inventory/branches/{branch_id}/availability"
        )
        assert bulk_r.status_code == 200
        bulk = {row["menu_id"]: row for row in bulk_r.json()}
        assert len(bulk) == 32, f"branch {branch_id} expected 32 active items"

        for menu_id in ["MENU001", "MENU004", "MENU010", "MENU015", "MENU022"]:
            single_r = await client.get(
                f"/api/v1/inventory/availability/{menu_id}?branch_id={branch_id}"
            )
            single = single_r.json()
            assert bulk[menu_id]["max_portions"] == single["max_portions"], \
                (
                    f"{menu_id}@{branch_id}: "
                    f"bulk={bulk[menu_id]['max_portions']} "
                    f"single={single['max_portions']}"
                )
            assert bulk[menu_id]["status"] == single["status"]


@pytest.mark.asyncio
async def test_bulk_availability_by_category(client):
    r = await client.get("/api/v1/inventory/branches/UTG-KHI-001/availability?category=BBQ")
    assert r.status_code == 200
    assert len(r.json()) == 4
