"""
Pydantic DTOs for inventory-domain API responses.
"""
from __future__ import annotations

from datetime import datetime
from pydantic import BaseModel, ConfigDict


class BranchOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    branch_id: str
    branch_name: str
    address_demo: str | None = None
    tables_count: int
    seats: int
    hours: str
    status: str


class BranchStockOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    branch_id: str
    ingredient_id: str
    ingredient_name: str
    category: str
    unit: str
    opening: float
    received: float
    consumed: float
    wastage: float
    adjustment: float
    reserved: float
    on_hand: float
    available: float
    suggested_buy: float
    stock_status: str
    unit_cost_pkr: float
    stock_value_pkr: float
    reorder_level: float
    target_stock: float
    snapshot_at: datetime


class AvailabilityOut(BaseModel):
    menu_id: str
    branch_id: str
    catalog_status: str
    recipe_linked: bool
    max_portions: int
    status: str               # NOT_ACTIVE | NO_RECIPE | UNAVAILABLE | AVAILABLE
    limiting_ingredient_id: str | None = None
    limiting_ingredient_name: str | None = None
    reason: str | None = None
