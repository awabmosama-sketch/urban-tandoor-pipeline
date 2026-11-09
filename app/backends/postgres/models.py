"""SQLModel tables for the PostgreSQL / Neon backend.

Field names match the canonical JSON snapshots one-to-one, so the same
``data/json/<collection>.json`` files feed both MongoDB and PostgreSQL.

Foreign-key constraints are intentionally not declared at the database level:
the JSON snapshots are the contract and are already validated by the parser.
Omitting database FKs keeps ``utg-ingest --only menu`` order-independent (the
menu domain references branches that live in the inventory domain).
"""
from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import ARRAY, Column, Date, DateTime, Float, Numeric, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel

__all__ = [
    "ALL_MODELS",
    "COLLECTION_MODELS",
    "Addon",
    "AllergenGuide",
    "Branch",
    "BranchMenu",
    "BranchStock",
    "Category",
    "Deal",
    "DealItem",
    "DocumentChunk",
    "Ingredient",
    "InventoryLink",
    "ItemAddon",
    "ItemAlias",
    "MenuItem",
    "Recipe",
    "ServiceRule",
    "SourceDocument",
    "StockMovement",
    "Supplier",
    "Variant",
]


def _utcnow() -> datetime:
    return datetime.now(UTC)


class Category(SQLModel, table=True):
    __tablename__ = "categories"

    category_id: str = Field(primary_key=True, max_length=16)
    category_name: str = Field(max_length=64)
    sort_order: int = Field(default=0)
    status: str = Field(default="Active", max_length=16)
    customer_description: str | None = Field(default=None)


class AllergenGuide(SQLModel, table=True):
    __tablename__ = "allergen_guide"

    allergen_code: str = Field(primary_key=True, max_length=16)
    display_name: str = Field(max_length=64)
    status: str = Field(default="Unverified", max_length=32)
    use_policy: str = Field(max_length=256)


class ServiceRule(SQLModel, table=True):
    __tablename__ = "service_rules"

    rule_id: str = Field(primary_key=True, max_length=16)
    rule_name: str = Field(max_length=128)
    value: str = Field(max_length=128)
    applies_to: str = Field(max_length=64)
    verification_status: str = Field(max_length=64)
    comment: str | None = Field(default=None)


class Deal(SQLModel, table=True):
    __tablename__ = "deals"

    deal_id: str = Field(primary_key=True, max_length=16)
    deal_name: str = Field(max_length=128)
    deal_type: str = Field(max_length=32)
    description: str
    deal_price_pkr: Decimal = Field(sa_type=Numeric(10, 2))
    currency: str = Field(default="PKR", max_length=8)
    approval_status: str = Field(max_length=32)
    branches: str = Field(max_length=32)
    service_window: str = Field(max_length=64)
    min_spend_pkr: Decimal | None = Field(default=None, sa_type=Numeric(10, 2))
    stack_bank_discount: bool = Field(default=False)
    policy_notes: str | None = Field(default=None)


class MenuItem(SQLModel, table=True):
    __tablename__ = "menu_items"

    menu_id: str = Field(primary_key=True, max_length=16)
    item_name: str = Field(max_length=128, index=True)
    category_id: str = Field(max_length=16, index=True)
    category: str = Field(max_length=64)
    description: str | None = Field(default=None)
    base_price_pkr: Decimal = Field(sa_type=Numeric(10, 2))
    currency: str = Field(default="PKR", max_length=8)
    item_type: str = Field(max_length=16)
    catalog_status: str = Field(max_length=32, index=True)
    recipe_linked: bool = Field(default=False)
    prep_time_min: int = Field(default=0)
    dietary_hint: str | None = Field(default=None, max_length=128)
    allergen_hint: str | None = Field(default=None, max_length=128)
    allergen_verified: bool = Field(default=False)
    service_window: str = Field(default="All day", max_length=64)
    upsell_eligible: bool = Field(default=True)
    slug: str = Field(max_length=128, unique=True)
    data_provenance: str = Field(default="Synthetic demo pricing", max_length=64)
    updated_at: datetime = Field(
        default_factory=_utcnow,
        sa_type=DateTime(timezone=True),
    )


class Variant(SQLModel, table=True):
    __tablename__ = "variants"

    variant_id: str = Field(primary_key=True, max_length=32)
    menu_id: str = Field(max_length=16, index=True)
    variant_name: str = Field(max_length=64)
    price_pkr: Decimal = Field(sa_type=Numeric(10, 2))
    recipe_multiplier_est: float = Field(default=1.0)
    shown_in_menu: bool = Field(default=True)
    approved_for_orders: bool = Field(default=False)
    operational_notes: str | None = Field(default=None)


class ItemAlias(SQLModel, table=True):
    __tablename__ = "item_aliases"

    alias_id: str = Field(primary_key=True, max_length=16)
    menu_id: str = Field(max_length=16, index=True)
    customer_phrase: str = Field(max_length=128, index=True)
    language: str = Field(max_length=32)
    alias_notes: str | None = Field(default=None, max_length=128)


class BranchMenu(SQLModel, table=True):
    __tablename__ = "branch_menu"

    branch_menu_id: str = Field(primary_key=True, max_length=32)
    branch_id: str = Field(max_length=16, index=True)
    branch_name: str = Field(max_length=64)
    menu_id: str = Field(max_length=16, index=True)
    enabled_for_order: bool = Field(default=False)
    price_pkr: Decimal = Field(sa_type=Numeric(10, 2))
    base_variant_orderable: bool = Field(default=False)
    stock_decision: str = Field(max_length=32)
    snapshot_max_portions: int | None = Field(default=None)
    notes: str | None = Field(default=None)


class InventoryLink(SQLModel, table=True):
    __tablename__ = "inventory_links"

    menu_id: str = Field(primary_key=True, max_length=16)
    branch_id: str = Field(primary_key=True, max_length=16)
    recipe_linked: bool = Field(default=False)
    snapshot_max_portions: int | None = Field(default=None)
    recipe_link_status: str = Field(max_length=64)
    runtime_check_policy: str = Field(max_length=128)


class Addon(SQLModel, table=True):
    __tablename__ = "addons"

    addon_id: str = Field(primary_key=True, max_length=16)
    addon_name: str = Field(max_length=64)
    price_pkr: Decimal = Field(sa_type=Numeric(10, 2))
    category: str = Field(max_length=32)
    allergen_hint: str | None = Field(default=None, max_length=64)
    ingredient_id: str | None = Field(default=None, max_length=16)
    qty_ingredient_units: float | None = Field(default=None)
    shown_in_menu: bool = Field(default=True)
    order_status: str = Field(max_length=64)


class ItemAddon(SQLModel, table=True):
    __tablename__ = "item_addons"

    mapping_id: str = Field(primary_key=True, max_length=16)
    menu_id: str = Field(max_length=16, index=True)
    addon_id: str = Field(max_length=16, index=True)
    selectable: bool = Field(default=False)
    operational_notes: str | None = Field(default=None)


class DealItem(SQLModel, table=True):
    __tablename__ = "deal_items"

    deal_id: str = Field(primary_key=True, max_length=16)
    menu_id: str = Field(primary_key=True, max_length=16)
    variant_id: str = Field(primary_key=True, max_length=32)
    item_name: str = Field(max_length=128)
    qty: int = Field(default=1)


class Supplier(SQLModel, table=True):
    __tablename__ = "suppliers"

    supplier_id: str = Field(primary_key=True, max_length=16)
    supplier_name: str = Field(max_length=128)
    supply_category: str = Field(max_length=128)
    contact: str | None = Field(default=None, max_length=64)
    verification: str = Field(default="Not verified", max_length=32)


class Branch(SQLModel, table=True):
    __tablename__ = "branches"

    branch_id: str = Field(primary_key=True, max_length=16)
    branch_name: str = Field(max_length=64)
    address_demo: str | None = Field(default=None)
    tables_count: int = Field(default=0)  # workbook column "Tables"
    seats: int = Field(default=0)
    hours: str = Field(default="24/7", max_length=32)
    status: str = Field(default="Active", max_length=16)


class Ingredient(SQLModel, table=True):
    __tablename__ = "ingredients"

    ingredient_id: str = Field(primary_key=True, max_length=16)
    ingredient_name: str = Field(max_length=128, index=True)
    category: str = Field(max_length=32)
    unit: str = Field(max_length=16)
    unit_cost_pkr: Decimal = Field(sa_type=Numeric(10, 2))
    default_reorder: float = Field(default=0.0)
    default_target: float = Field(default=0.0)
    supplier_id: str | None = Field(default=None, max_length=16, index=True)
    status: str = Field(default="Active", max_length=16)


class BranchStock(SQLModel, table=True):
    __tablename__ = "branch_stock"

    branch_id: str = Field(primary_key=True, max_length=16)
    ingredient_id: str = Field(primary_key=True, max_length=16, index=True)
    ingredient_name: str = Field(max_length=128)
    category: str = Field(max_length=32)
    unit: str = Field(max_length=16)

    # --- raw inputs (from Excel) ---
    opening: float = Field(default=0.0)
    received: float = Field(default=0.0)
    consumed: float = Field(default=0.0)
    wastage: float = Field(default=0.0)
    adjustment: float = Field(default=0.0)
    reserved: float = Field(default=0.0)

    # --- computed values (populated by ingestion) ---
    on_hand: float | None = Field(default=None)
    available: float | None = Field(default=None)
    suggested_buy: float | None = Field(default=None)
    stock_status: str | None = Field(default=None, max_length=16, index=True)
    stock_value_pkr: Decimal | None = Field(default=None, sa_type=Numeric(12, 2))

    # --- planning metadata ---
    reorder_level: float = Field(default=0.0)
    target_stock: float = Field(default=0.0)
    unit_cost_pkr: Decimal = Field(sa_type=Numeric(10, 2))
    snapshot_at: datetime = Field(
        default_factory=_utcnow,
        sa_type=DateTime(timezone=True),
    )


class Recipe(SQLModel, table=True):
    __tablename__ = "recipes"

    menu_id: str = Field(primary_key=True, max_length=16)
    ingredient_id: str = Field(primary_key=True, max_length=16, index=True)
    menu_item: str = Field(max_length=128)  # denormalized, from workbook "Menu_Item"
    category: str = Field(max_length=64)  # denormalized, from workbook "Category"
    qty_per_portion: float = Field(ge=0.0)  # ingredient units per 1 menu serving
    ingredient_name: str = Field(max_length=128)  # denormalized, from workbook


class StockMovement(SQLModel, table=True):
    __tablename__ = "stock_movements"

    movement_id: str = Field(primary_key=True, max_length=16)
    movement_date: date = Field(sa_type=Date)
    branch_id: str = Field(max_length=16, index=True)
    ingredient_id: str = Field(max_length=16, index=True)
    movement_type: str = Field(max_length=32)
    qty_signed: float
    unit: str = Field(max_length=16)
    reference: str | None = Field(default=None, max_length=64)
    reason: str | None = Field(default=None, max_length=128)
    data_type: str = Field(default="Demo", max_length=16)


class SourceDocument(SQLModel, table=True):
    __tablename__ = "source_documents"

    document_id: str = Field(primary_key=True, max_length=128)
    source_path: str = Field(max_length=512)
    source_type: str = Field(max_length=32)  # "docx" | "xlsx_sheet" | "text"
    checksum: str = Field(max_length=64, index=True)  # sha256 hex
    title: str | None = Field(default=None, max_length=256)
    loaded_at: datetime = Field(
        default_factory=_utcnow,
        sa_type=DateTime(timezone=True),
    )
    metadata_json: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSONB, nullable=False, server_default=text("'{}'::jsonb")),
    )


class DocumentChunk(SQLModel, table=True):
    __tablename__ = "document_chunks"

    chunk_id: str = Field(primary_key=True, max_length=160)
    document_id: str = Field(max_length=128, index=True)
    ordinal: int = Field(default=0)
    content: str = Field(sa_column=Column(Text, nullable=False))
    token_count: int = Field(default=0)
    section: str | None = Field(default=None, max_length=256)
    # Embeddings are generated at import time. A plain float array keeps the
    # backend portable (no pgvector extension required) and ranking happens in
    # the application process, mirroring the MongoDB backend.
    embedding: list[float] | None = Field(
        default=None,
        sa_column=Column(ARRAY(Float), nullable=True),
    )
    embedded_at: datetime | None = Field(
        default=None,
        sa_type=DateTime(timezone=True),
    )
    metadata_json: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSONB, nullable=False, server_default=text("'{}'::jsonb")),
    )


COLLECTION_MODELS: dict[str, type[SQLModel]] = {
    "categories": Category,
    "menu_items": MenuItem,
    "variants": Variant,
    "addons": Addon,
    "item_addons": ItemAddon,
    "item_aliases": ItemAlias,
    "branch_menu": BranchMenu,
    "inventory_links": InventoryLink,
    "deals": Deal,
    "deal_items": DealItem,
    "allergen_guide": AllergenGuide,
    "service_rules": ServiceRule,
    "suppliers": Supplier,
    "ingredients": Ingredient,
    "branches": Branch,
    "branch_stock": BranchStock,
    "recipes": Recipe,
    "stock_movements": StockMovement,
    "source_documents": SourceDocument,
    "document_chunks": DocumentChunk,
}

ALL_MODELS: tuple[type[SQLModel], ...] = tuple(COLLECTION_MODELS.values())
