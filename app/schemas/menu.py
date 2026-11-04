"""
Pydantic DTOs for menu-domain API responses.
Money fields use float (JSON-safe; PKR prices fit float64 without precision loss).
from_attributes=True lets us return SQLModel instances directly.
"""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class CategoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    category_id: str
    category_name: str
    sort_order: int
    status: str
    customer_description: str | None = None


class VariantOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    variant_id: str
    variant_name: str
    price_pkr: float
    shown_in_menu: bool
    approved_for_orders: bool


class AddonOut(BaseModel):
    addon_id: str
    addon_name: str
    price_pkr: float
    category: str
    selectable: bool          # from ItemAddon.selectable
    allergen_hint: str | None = None


class MenuItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    menu_id: str
    item_name: str
    category: str
    description: str | None = None
    base_price_pkr: float
    item_type: str
    catalog_status: str
    prep_time_min: int
    dietary_hint: str | None = None
    allergen_hint: str | None = None
    service_window: str


class MenuItemDetail(MenuItemOut):
    variants: list[VariantOut] = Field(default_factory=list)


class AliasOut(BaseModel):
    alias_id: str
    menu_id: str
    item_name: str            # denormalized from join
    customer_phrase: str
    language: str
    alias_notes: str | None = None
