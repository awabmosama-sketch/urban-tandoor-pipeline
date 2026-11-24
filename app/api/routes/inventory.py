"""
Inventory read APIs: branches, branch stock and availability.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app.api.deps import DatabaseDep
from app.schemas.inventory import AvailabilityOut, BranchOut, BranchStockOut
from app.services.availability import (
    compute_availability_bulk,
    compute_availability_single,
)

router = APIRouter(prefix="/inventory", tags=["inventory"])


@router.get("/branches", response_model=list[BranchOut])
async def list_branches(db: DatabaseDep) -> list[dict]:
    return await db.branches.find({}).sort("branch_id", 1).to_list(length=None)


@router.get("/branches/{branch_id}/stock", response_model=list[BranchStockOut])
async def list_branch_stock(
    branch_id: str,
    db: DatabaseDep,
    limit: int = Query(200, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> list[dict]:
    branch = await db.branches.find_one({"branch_id": branch_id})
    if branch is None:
        raise HTTPException(status_code=404, detail="Branch not found")

    return await db.branch_stock.find({"branch_id": branch_id}).sort(
        "ingredient_id", 1
    ).skip(offset).limit(limit).to_list(length=None)


@router.get(
    "/branches/{branch_id}/stock/{ingredient_id}",
    response_model=BranchStockOut,
)
async def get_branch_stock_item(
    branch_id: str,
    ingredient_id: str,
    db: DatabaseDep,
) -> dict:
    branch = await db.branches.find_one({"branch_id": branch_id})
    if branch is None:
        raise HTTPException(status_code=404, detail="Branch not found")

    row = await db.branch_stock.find_one(
        {"branch_id": branch_id, "ingredient_id": ingredient_id}
    )
    if row is None:
        raise HTTPException(
            status_code=404,
            detail="Ingredient not in this branch's stock",
        )
    return row


@router.get("/availability/{menu_id}", response_model=AvailabilityOut)
async def get_availability(
    menu_id: str,
    db: DatabaseDep,
    branch_id: str = Query(..., min_length=1),
) -> AvailabilityOut:
    result = await compute_availability_single(
        db, menu_id=menu_id, branch_id=branch_id,
    )
    if result is None:
        item = await db.menu_items.find_one({"menu_id": menu_id})
        if item is None:
            raise HTTPException(status_code=404, detail="Menu item not found")
        raise HTTPException(status_code=404, detail="Branch not found")
    return result


@router.get(
    "/branches/{branch_id}/availability",
    response_model=list[AvailabilityOut],
)
async def get_branch_availability(
    branch_id: str,
    db: DatabaseDep,
    category: str | None = None,
) -> list[AvailabilityOut]:
    result = await compute_availability_bulk(
        db, branch_id=branch_id, category=category,
    )
    if result is None:
        raise HTTPException(status_code=404, detail="Branch not found")
    return result
