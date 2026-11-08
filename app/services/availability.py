"""
Availability service (MongoDB).

The formula (identical to the workbook's cached Snapshot_Max_Portions):
    max_portions = min(floor(branch_stock.available / recipe.qty_per_portion))
    over every ingredient line in the menu item's recipe.

Status precedence (documented and enforced):
    NOT_ACTIVE       catalog_status != "Active" → cannot order (regardless of stock)
    NO_RECIPE        Active item but no recipe lines → config error, cannot compute
    UNAVAILABLE      recipe exists, stock insufficient (>=1 line gives 0 portions)
    AVAILABLE        recipe exists, stock sufficient

Missing BranchStock rows are treated as available=0, so the item is
UNAVAILABLE rather than silently skipped.
"""
from __future__ import annotations

from dataclasses import dataclass

from motor.motor_asyncio import AsyncIOMotorDatabase

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
    for line in lines:
        if line.qty_per_portion <= 0:
            return 0, line.ingredient_id, line.ingredient_name
        available = line.available if line.available is not None else 0.0
        portions = int(available / line.qty_per_portion)  # floor for non-negative
        if min_portions is None or portions < min_portions:
            min_portions = portions
            limit_id = line.ingredient_id
            limit_name = line.ingredient_name
    return min_portions or 0, limit_id, limit_name


async def _load_recipe_lines(
    db: AsyncIOMotorDatabase,
    branch_id: str,
    menu_ids: list[str] | None = None,
) -> dict[str, list[_RecipeLine]]:
    """Load recipe lines for one or all menu items, with branch availability."""
    recipe_filter: dict = {}
    if menu_ids is not None:
        if not menu_ids:
            return {}
        recipe_filter = {"menu_id": {"$in": menu_ids}}

    recipes = await db.recipes.find(recipe_filter).to_list(length=None)
    if not recipes:
        return {}

    ingredient_ids = sorted({row["ingredient_id"] for row in recipes})
    ingredient_docs = await db.ingredients.find(
        {"ingredient_id": {"$in": ingredient_ids}},
        {"ingredient_id": 1, "ingredient_name": 1},
    ).to_list(length=None)
    ingredient_names = {
        row["ingredient_id"]: row.get("ingredient_name", row["ingredient_id"])
        for row in ingredient_docs
    }

    stock_docs = await db.branch_stock.find(
        {
            "branch_id": branch_id,
            "ingredient_id": {"$in": ingredient_ids},
        },
        {"ingredient_id": 1, "available": 1},
    ).to_list(length=None)
    available_by_ingredient = {
        row["ingredient_id"]: float(row.get("available") or 0.0)
        for row in stock_docs
    }

    grouped: dict[str, list[_RecipeLine]] = {}
    for row in recipes:
        ingredient_id = row["ingredient_id"]
        grouped.setdefault(row["menu_id"], []).append(
            _RecipeLine(
                ingredient_id=ingredient_id,
                ingredient_name=ingredient_names.get(
                    ingredient_id,
                    row.get("ingredient_name", ingredient_id),
                ),
                qty_per_portion=float(row["qty_per_portion"]),
                available=available_by_ingredient.get(ingredient_id),
            )
        )
    return grouped


async def compute_availability_single(
    db: AsyncIOMotorDatabase,
    *,
    menu_id: str,
    branch_id: str,
) -> AvailabilityOut | None:
    """Returns None if menu_id or branch_id doesn't exist (caller returns 404)."""
    item = await db.menu_items.find_one({"menu_id": menu_id})
    if item is None:
        return None
    branch = await db.branches.find_one({"branch_id": branch_id})
    if branch is None:
        return None

    if item.get("catalog_status") != "Active":
        return AvailabilityOut(
            menu_id=menu_id,
            branch_id=branch_id,
            catalog_status=item.get("catalog_status", ""),
            recipe_linked=bool(item.get("recipe_linked")),
            max_portions=0,
            status="NOT_ACTIVE",
            reason=f"catalog_status is {item.get('catalog_status')!r}",
        )

    grouped = await _load_recipe_lines(db, branch_id, [menu_id])
    lines = grouped.get(menu_id, [])
    if not lines:
        return AvailabilityOut(
            menu_id=menu_id,
            branch_id=branch_id,
            catalog_status=item.get("catalog_status", ""),
            recipe_linked=bool(item.get("recipe_linked")),
            max_portions=0,
            status="NO_RECIPE",
            reason="no recipe lines found for this menu item",
        )

    max_portions, limit_id, limit_name = _compute_min_portions(lines)
    status = "AVAILABLE" if max_portions > 0 else "UNAVAILABLE"
    return AvailabilityOut(
        menu_id=menu_id,
        branch_id=branch_id,
        catalog_status=item.get("catalog_status", ""),
        recipe_linked=bool(item.get("recipe_linked")),
        max_portions=max_portions,
        status=status,
        limiting_ingredient_id=limit_id,
        limiting_ingredient_name=limit_name,
        reason=None if status == "AVAILABLE" else f"limiting: {limit_name}",
    )


async def compute_availability_bulk(
    db: AsyncIOMotorDatabase,
    *,
    branch_id: str,
    category: str | None = None,
) -> list[AvailabilityOut] | None:
    """Returns None if branch_id doesn't exist."""
    branch = await db.branches.find_one({"branch_id": branch_id})
    if branch is None:
        return None

    item_filter: dict = {"catalog_status": "Active"}
    if category:
        item_filter["category"] = category
    items = await db.menu_items.find(item_filter).sort("menu_id", 1).to_list(length=None)
    if not items:
        return []

    menu_ids = [item["menu_id"] for item in items]
    grouped = await _load_recipe_lines(db, branch_id, menu_ids)

    output: list[AvailabilityOut] = []
    for item in items:
        menu_id = item["menu_id"]
        lines = grouped.get(menu_id, [])
        if not lines:
            output.append(
                AvailabilityOut(
                    menu_id=menu_id,
                    branch_id=branch_id,
                    catalog_status=item.get("catalog_status", ""),
                    recipe_linked=bool(item.get("recipe_linked")),
                    max_portions=0,
                    status="NO_RECIPE",
                    reason="no recipe lines found",
                )
            )
            continue
        max_portions, limit_id, limit_name = _compute_min_portions(lines)
        status = "AVAILABLE" if max_portions > 0 else "UNAVAILABLE"
        output.append(
            AvailabilityOut(
                menu_id=menu_id,
                branch_id=branch_id,
                catalog_status=item.get("catalog_status", ""),
                recipe_linked=bool(item.get("recipe_linked")),
                max_portions=max_portions,
                status=status,
                limiting_ingredient_id=limit_id,
                limiting_ingredient_name=limit_name,
                reason=None if status == "AVAILABLE" else f"limiting: {limit_name}",
            )
        )
    return output
