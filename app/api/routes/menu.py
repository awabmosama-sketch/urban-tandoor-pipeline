"""
Menu read APIs: categories, items, item detail, variants, addons and aliases.

MongoDB documents are returned and Pydantic ``response_model`` definitions
filter fields and coerce money to JSON-safe floats.
"""
from __future__ import annotations

import re

from fastapi import APIRouter, HTTPException, Query

from app.api.deps import DatabaseDep
from app.schemas.menu import (
    AddonOut,
    AliasOut,
    CategoryOut,
    MenuItemDetail,
    MenuItemOut,
    VariantOut,
)

CATALOG_STATUS_ACTIVE = "Active"
CATALOG_STATUS_ALL = "all"

router = APIRouter(prefix="/menu", tags=["menu"])


@router.get("/categories", response_model=list[CategoryOut])
async def list_categories(db: DatabaseDep) -> list[dict]:
    return await db.categories.find({}).sort("sort_order", 1).to_list(length=None)


@router.get("/items", response_model=list[MenuItemOut])
async def list_menu_items(
    db: DatabaseDep,
    category: str | None = None,
    catalog_status: str = CATALOG_STATUS_ACTIVE,
    q: str | None = None,
    limit: int = Query(200, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> list[dict]:
    query: dict = {}
    if category:
        query["category"] = category
    if catalog_status != CATALOG_STATUS_ALL:
        query["catalog_status"] = catalog_status
    if q:
        query["item_name"] = {"$regex": re.escape(q), "$options": "i"}
    return await db.menu_items.find(query).sort("menu_id", 1).skip(offset).limit(limit).to_list(
        length=None
    )


@router.get("/items/{menu_id}", response_model=MenuItemDetail)
async def get_menu_item(menu_id: str, db: DatabaseDep) -> MenuItemDetail:
    item = await db.menu_items.find_one({"menu_id": menu_id})
    if item is None:
        raise HTTPException(status_code=404, detail="Menu item not found")

    variants = await db.variants.find(
        {"menu_id": menu_id, "shown_in_menu": True}
    ).sort("price_pkr", 1).to_list(length=None)

    detail = MenuItemDetail(**item)
    detail.variants = [VariantOut(**variant) for variant in variants]
    return detail


@router.get("/items/{menu_id}/variants", response_model=list[VariantOut])
async def list_menu_item_variants(menu_id: str, db: DatabaseDep) -> list[dict]:
    item = await db.menu_items.find_one({"menu_id": menu_id})
    if item is None:
        raise HTTPException(status_code=404, detail="Menu item not found")

    return await db.variants.find(
        {"menu_id": menu_id, "shown_in_menu": True}
    ).sort("price_pkr", 1).to_list(length=None)


@router.get("/items/{menu_id}/addons", response_model=list[AddonOut])
async def list_menu_item_addons(menu_id: str, db: DatabaseDep) -> list[AddonOut]:
    item = await db.menu_items.find_one({"menu_id": menu_id})
    if item is None:
        raise HTTPException(status_code=404, detail="Menu item not found")

    mappings = await db.item_addons.find(
        {"menu_id": menu_id},
        {"addon_id": 1, "selectable": 1},
    ).sort("addon_id", 1).to_list(length=None)
    if not mappings:
        return []

    addon_ids = [mapping["addon_id"] for mapping in mappings]
    addons = await db.addons.find({"addon_id": {"$in": addon_ids}}).to_list(length=None)
    addons_by_id = {addon["addon_id"]: addon for addon in addons}

    output: list[AddonOut] = []
    for mapping in mappings:
        addon = addons_by_id.get(mapping["addon_id"])
        if addon is None:
            continue
        output.append(
            AddonOut(
                addon_id=addon["addon_id"],
                addon_name=addon["addon_name"],
                price_pkr=float(addon["price_pkr"]),
                category=addon["category"],
                selectable=bool(mapping.get("selectable")),
                allergen_hint=addon.get("allergen_hint"),
            )
        )
    return output


@router.get("/aliases", response_model=list[AliasOut])
async def list_aliases(
    db: DatabaseDep,
    phrase: str = Query(..., min_length=1),
    limit: int = Query(20, ge=1, le=100),
) -> list[AliasOut]:
    aliases = await db.item_aliases.find(
        {"customer_phrase": {"$regex": re.escape(phrase), "$options": "i"}}
    ).sort("alias_id", 1).limit(limit).to_list(length=None)
    if not aliases:
        return []

    menu_ids = sorted({alias["menu_id"] for alias in aliases})
    items = await db.menu_items.find(
        {"menu_id": {"$in": menu_ids}},
        {"menu_id": 1, "item_name": 1},
    ).to_list(length=None)
    item_names = {item["menu_id"]: item.get("item_name", "") for item in items}

    return [
        AliasOut(
            alias_id=alias["alias_id"],
            menu_id=alias["menu_id"],
            item_name=item_names.get(alias["menu_id"], ""),
            customer_phrase=alias["customer_phrase"],
            language=alias["language"],
            alias_notes=alias.get("alias_notes"),
        )
        for alias in aliases
    ]
