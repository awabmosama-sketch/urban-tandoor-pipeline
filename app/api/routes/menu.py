"""
Menu read APIs: categories, items, item detail, variants, addons and aliases.

All responses are Pydantic-serialized via ``response_model`` so Decimal money
columns become JSON-safe floats consistently.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select

from app.api.deps import SessionDep
from app.models import Addon, Category, ItemAddon, ItemAlias, MenuItem, Variant
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
async def list_categories(session: SessionDep) -> list[Category]:
    stmt = select(Category).order_by(Category.sort_order)
    return list((await session.execute(stmt)).scalars().all())


@router.get("/items", response_model=list[MenuItemOut])
async def list_menu_items(
    session: SessionDep,
    category: str | None = None,
    catalog_status: str = CATALOG_STATUS_ACTIVE,
    q: str | None = None,
    limit: int = Query(200, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> list[MenuItem]:
    stmt = select(MenuItem)
    if category:
        stmt = stmt.where(MenuItem.category == category)
    if catalog_status != CATALOG_STATUS_ALL:
        stmt = stmt.where(MenuItem.catalog_status == catalog_status)
    if q:
        stmt = stmt.where(MenuItem.item_name.ilike(f"%{q}%"))
    stmt = stmt.order_by(MenuItem.menu_id).limit(limit).offset(offset)
    return list((await session.execute(stmt)).scalars().all())


@router.get("/items/{menu_id}", response_model=MenuItemDetail)
async def get_menu_item(menu_id: str, session: SessionDep) -> MenuItemDetail:
    item = await session.get(MenuItem, menu_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Menu item not found")

    variant_stmt = (
        select(Variant)
        .where(Variant.menu_id == menu_id, Variant.shown_in_menu.is_(True))
        .order_by(Variant.price_pkr.asc())
    )
    variants = (await session.execute(variant_stmt)).scalars().all()

    detail = MenuItemDetail.model_validate(item)
    detail.variants = [VariantOut.model_validate(v) for v in variants]
    return detail


@router.get("/items/{menu_id}/variants", response_model=list[VariantOut])
async def list_menu_item_variants(menu_id: str, session: SessionDep) -> list[Variant]:
    item = await session.get(MenuItem, menu_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Menu item not found")

    stmt = (
        select(Variant)
        .where(Variant.menu_id == menu_id, Variant.shown_in_menu.is_(True))
        .order_by(Variant.price_pkr.asc())
    )
    return list((await session.execute(stmt)).scalars().all())


@router.get("/items/{menu_id}/addons", response_model=list[AddonOut])
async def list_menu_item_addons(menu_id: str, session: SessionDep) -> list[AddonOut]:
    item = await session.get(MenuItem, menu_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Menu item not found")

    stmt = (
        select(Addon, ItemAddon.selectable)
        .join(ItemAddon, ItemAddon.addon_id == Addon.addon_id)
        .where(ItemAddon.menu_id == menu_id)
        .order_by(Addon.addon_id)
    )
    rows = (await session.execute(stmt)).all()
    return [
        AddonOut(
            addon_id=addon.addon_id,
            addon_name=addon.addon_name,
            price_pkr=float(addon.price_pkr),
            category=addon.category,
            selectable=bool(selectable),
            allergen_hint=addon.allergen_hint,
        )
        for addon, selectable in rows
    ]


@router.get("/aliases", response_model=list[AliasOut])
async def list_aliases(
    session: SessionDep,
    phrase: str = Query(..., min_length=1),
    limit: int = Query(20, ge=1, le=100),
) -> list[AliasOut]:
    stmt = (
        select(ItemAlias, MenuItem.item_name)
        .join(MenuItem, MenuItem.menu_id == ItemAlias.menu_id)
        .where(ItemAlias.customer_phrase.ilike(f"%{phrase}%"))
        .order_by(ItemAlias.alias_id)
        .limit(limit)
    )
    rows = (await session.execute(stmt)).all()
    return [
        AliasOut(
            alias_id=alias.alias_id,
            menu_id=alias.menu_id,
            item_name=item_name,
            customer_phrase=alias.customer_phrase,
            language=alias.language,
            alias_notes=alias.alias_notes,
        )
        for alias, item_name in rows
    ]
