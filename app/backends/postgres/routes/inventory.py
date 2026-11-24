"""
Inventory read APIs (PostgreSQL): branches, branch stock and availability.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select

from app.backends.postgres.deps import SessionDep
from app.backends.postgres.models import Branch, BranchStock, MenuItem
from app.backends.postgres.services.availability import (
    compute_availability_bulk,
    compute_availability_single,
)
from app.schemas.inventory import AvailabilityOut, BranchOut, BranchStockOut

router = APIRouter(prefix="/inventory", tags=["inventory"])


@router.get("/branches", response_model=list[BranchOut])
async def list_branches(session: SessionDep) -> list[Branch]:
    stmt = select(Branch).order_by(Branch.branch_id)
    return list((await session.execute(stmt)).scalars().all())


@router.get("/branches/{branch_id}/stock", response_model=list[BranchStockOut])
async def list_branch_stock(
    branch_id: str,
    session: SessionDep,
    limit: int = Query(200, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> list[BranchStock]:
    branch = await session.get(Branch, branch_id)
    if branch is None:
        raise HTTPException(status_code=404, detail="Branch not found")

    stmt = (
        select(BranchStock)
        .where(BranchStock.branch_id == branch_id)
        .order_by(BranchStock.ingredient_id)
        .limit(limit)
        .offset(offset)
    )
    return list((await session.execute(stmt)).scalars().all())


@router.get(
    "/branches/{branch_id}/stock/{ingredient_id}",
    response_model=BranchStockOut,
)
async def get_branch_stock_item(
    branch_id: str,
    ingredient_id: str,
    session: SessionDep,
) -> BranchStock:
    branch = await session.get(Branch, branch_id)
    if branch is None:
        raise HTTPException(status_code=404, detail="Branch not found")

    row = await session.get(BranchStock, (branch_id, ingredient_id))
    if row is None:
        raise HTTPException(
            status_code=404,
            detail="Ingredient not in this branch's stock",
        )
    return row


@router.get("/availability/{menu_id}", response_model=AvailabilityOut)
async def get_availability(
    menu_id: str,
    session: SessionDep,
    branch_id: str = Query(..., min_length=1),
) -> AvailabilityOut:
    result = await compute_availability_single(
        session, menu_id=menu_id, branch_id=branch_id,
    )
    if result is None:
        item = await session.get(MenuItem, menu_id)
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
    session: SessionDep,
    category: str | None = None,
) -> list[AvailabilityOut]:
    result = await compute_availability_bulk(
        session, branch_id=branch_id, category=category,
    )
    if result is None:
        raise HTTPException(status_code=404, detail="Branch not found")
    return result
