"""
Availability service.

The formula (identical to the workbook's cached Snapshot_Max_Portions):
    max_portions = min(floor(branch_stock.available / recipe.qty_per_portion))
    over every ingredient line in the menu item's recipe.

Status precedence (documented and enforced):
    NOT_ACTIVE       catalog_status != "Active" → cannot order (regardless of stock)
    NO_RECIPE        Active item but no recipe lines → config error, cannot compute
    UNAVAILABLE      recipe exists, stock insufficient (>=1 line gives 0 portions)
    AVAILABLE        recipe exists, stock sufficient

A LEFT JOIN means missing BranchStock rows are treated as available=0 — the
result is UNAVAILABLE for that item, not a silent skip.
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Branch, BranchStock, Ingredient, MenuItem, Recipe
from app.schemas.inventory import AvailabilityOut


@dataclass
class _RecipeLine:
    ingredient_id: str
    ingredient_name: str
    qty_per_portion: float
    available: float | None


def _compute_min_portions(
    lines: list[_RecipeLine],
) -> tuple[int, str | None, str | None]:
    """Returns (max_portions, limiting_ingredient_id, limiting_ingredient_name)."""
    if not lines:
        return 0, None, None
    min_portions: int | None = None
    limit_id: str | None = None
    limit_name: str | None = None
    for ln in lines:
        if ln.qty_per_portion <= 0:
            return 0, ln.ingredient_id, ln.ingredient_name
        avail = ln.available if ln.available is not None else 0.0
        portions = int(avail / ln.qty_per_portion)   # floor for non-negative
        if min_portions is None or portions < min_portions:
            min_portions = portions
            limit_id = ln.ingredient_id
            limit_name = ln.ingredient_name
    return min_portions or 0, limit_id, limit_name


async def _load_recipe_lines(
    session: AsyncSession,
    branch_id: str,
    menu_ids: list[str] | None = None,
) -> dict[str, list[_RecipeLine]]:
    """One query. Groups rows by menu_id. If menu_ids is None, loads ALL."""
    stmt = (
        select(
            Recipe.menu_id,
            Recipe.ingredient_id,
            Recipe.qty_per_portion,
            BranchStock.available,
            Ingredient.ingredient_name,
        )
        .select_from(Recipe)
        .join(Ingredient, Ingredient.ingredient_id == Recipe.ingredient_id)
        .outerjoin(
            BranchStock,
            and_(
                BranchStock.ingredient_id == Recipe.ingredient_id,
                BranchStock.branch_id == branch_id,
            ),
        )
    )
    if menu_ids is not None:
        if not menu_ids:
            return {}
        stmt = stmt.where(Recipe.menu_id.in_(menu_ids))
    rows = (await session.execute(stmt)).all()
    grouped: dict[str, list[_RecipeLine]] = {}
    for menu_id, ing_id, qty, avail, ing_name in rows:
        grouped.setdefault(menu_id, []).append(
            _RecipeLine(
                ingredient_id=ing_id,
                ingredient_name=ing_name,
                qty_per_portion=float(qty),
                available=float(avail) if avail is not None else None,
            )
        )
    return grouped


async def compute_availability_single(
    session: AsyncSession, *, menu_id: str, branch_id: str,
) -> AvailabilityOut | None:
    """Returns None if menu_id or branch_id doesn't exist (caller returns 404).
    For a valid draft item, returns AvailabilityOut with status NOT_ACTIVE."""
    item = await session.get(MenuItem, menu_id)
    if item is None:
        return None
    branch = await session.get(Branch, branch_id)
    if branch is None:
        return None

    if item.catalog_status != "Active":
        return AvailabilityOut(
            menu_id=menu_id, branch_id=branch_id,
            catalog_status=item.catalog_status, recipe_linked=item.recipe_linked,
            max_portions=0, status="NOT_ACTIVE",
            reason=f"catalog_status is {item.catalog_status!r}",
        )

    grouped = await _load_recipe_lines(session, branch_id, [menu_id])
    lines = grouped.get(menu_id, [])
    if not lines:
        return AvailabilityOut(
            menu_id=menu_id, branch_id=branch_id,
            catalog_status=item.catalog_status, recipe_linked=item.recipe_linked,
            max_portions=0, status="NO_RECIPE",
            reason="no recipe lines found for this menu item",
        )

    max_p, limit_id, limit_name = _compute_min_portions(lines)
    status = "AVAILABLE" if max_p > 0 else "UNAVAILABLE"
    reason = None if status == "AVAILABLE" else f"limiting: {limit_name}"
    return AvailabilityOut(
        menu_id=menu_id, branch_id=branch_id,
        catalog_status=item.catalog_status, recipe_linked=item.recipe_linked,
        max_portions=max_p, status=status,
        limiting_ingredient_id=limit_id, limiting_ingredient_name=limit_name,
        reason=reason,
    )


async def compute_availability_bulk(
    session: AsyncSession, *, branch_id: str, category: str | None = None,
) -> list[AvailabilityOut] | None:
    """Returns None if branch_id doesn't exist."""
    branch = await session.get(Branch, branch_id)
    if branch is None:
        return None

    item_stmt = select(MenuItem).where(MenuItem.catalog_status == "Active")
    if category:
        item_stmt = item_stmt.where(MenuItem.category == category)
    items = (await session.execute(item_stmt.order_by(MenuItem.menu_id))).scalars().all()
    if not items:
        return []

    menu_ids = [it.menu_id for it in items]
    grouped = await _load_recipe_lines(session, branch_id, menu_ids)

    out: list[AvailabilityOut] = []
    for it in items:
        lines = grouped.get(it.menu_id, [])
        if not lines:
            out.append(AvailabilityOut(
                menu_id=it.menu_id, branch_id=branch_id,
                catalog_status=it.catalog_status, recipe_linked=it.recipe_linked,
                max_portions=0, status="NO_RECIPE",
                reason="no recipe lines found",
            ))
            continue
        max_p, limit_id, limit_name = _compute_min_portions(lines)
        status = "AVAILABLE" if max_p > 0 else "UNAVAILABLE"
        out.append(AvailabilityOut(
            menu_id=it.menu_id, branch_id=branch_id,
            catalog_status=it.catalog_status, recipe_linked=it.recipe_linked,
            max_portions=max_p, status=status,
            limiting_ingredient_id=limit_id, limiting_ingredient_name=limit_name,
            reason=None if status == "AVAILABLE" else f"limiting: {limit_name}",
        ))
    return out
