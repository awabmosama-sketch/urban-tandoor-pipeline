"""MongoDB collection names, natural keys and index definitions.

The relational schema is kept as one collection per former table. That makes
the JSON export easy to inspect and keeps the API field names unchanged.

Index specs are ``(field_names, create_index_kwargs)`` where every field is
indexed in ascending order. Compound specs use the same shape.
"""

from __future__ import annotations

from typing import Any

MENU_COLLECTIONS: tuple[str, ...] = (
    "categories",
    "menu_items",
    "variants",
    "addons",
    "item_addons",
    "item_aliases",
    "branch_menu",
    "inventory_links",
    "deals",
    "deal_items",
    "allergen_guide",
    "service_rules",
)

INVENTORY_COLLECTIONS: tuple[str, ...] = (
    "suppliers",
    "ingredients",
    "branches",
    "branch_stock",
    "recipes",
    "stock_movements",
)

DOCS_COLLECTIONS: tuple[str, ...] = (
    "source_documents",
    "document_chunks",
)

ALL_COLLECTIONS: tuple[str, ...] = (
    MENU_COLLECTIONS + INVENTORY_COLLECTIONS + DOCS_COLLECTIONS
)

# Natural keys used by the idempotent JSON upsert. Every key field is present
# in the exported JSON document.
NATURAL_KEYS: dict[str, tuple[str, ...]] = {
    "categories": ("category_id",),
    "menu_items": ("menu_id",),
    "variants": ("variant_id",),
    "addons": ("addon_id",),
    "item_addons": ("mapping_id",),
    "item_aliases": ("alias_id",),
    "branch_menu": ("branch_menu_id",),
    "inventory_links": ("menu_id", "branch_id"),
    "deals": ("deal_id",),
    "deal_items": ("deal_id", "menu_id", "variant_id"),
    "allergen_guide": ("allergen_code",),
    "service_rules": ("rule_id",),
    "suppliers": ("supplier_id",),
    "ingredients": ("ingredient_id",),
    "branches": ("branch_id",),
    "branch_stock": ("branch_id", "ingredient_id"),
    "recipes": ("menu_id", "ingredient_id"),
    "stock_movements": ("movement_id",),
    "source_documents": ("document_id",),
    "document_chunks": ("chunk_id",),
}

# Simple (single or compound) indexes: (field_names, create_index kwargs)
INDEX_SPECS: dict[str, list[tuple[tuple[str, ...], dict[str, Any]]]] = {
    "categories": [
        (("category_id",), {"unique": True}),
        (("sort_order",), {}),
    ],
    "menu_items": [
        (("menu_id",), {"unique": True}),
        (("category_id",), {}),
        (("category",), {}),
        (("catalog_status",), {}),
        (("slug",), {"unique": True}),
    ],
    "variants": [
        (("variant_id",), {"unique": True}),
        (("menu_id",), {}),
    ],
    "addons": [
        (("addon_id",), {"unique": True}),
        (("ingredient_id",), {}),
    ],
    "item_addons": [
        (("mapping_id",), {"unique": True}),
        (("menu_id",), {}),
        (("addon_id",), {}),
    ],
    "item_aliases": [
        (("alias_id",), {"unique": True}),
        (("menu_id",), {}),
        (("customer_phrase",), {}),
    ],
    "branch_menu": [
        (("branch_menu_id",), {"unique": True}),
        (("branch_id",), {}),
        (("menu_id",), {}),
    ],
    "inventory_links": [(("branch_id",), {})],
    "deals": [(("deal_id",), {"unique": True})],
    "deal_items": [],
    "allergen_guide": [(("allergen_code",), {"unique": True})],
    "service_rules": [(("rule_id",), {"unique": True})],
    "suppliers": [(("supplier_id",), {"unique": True})],
    "ingredients": [
        (("ingredient_id",), {"unique": True}),
        (("ingredient_name",), {}),
        (("supplier_id",), {}),
    ],
    "branches": [(("branch_id",), {"unique": True})],
    "branch_stock": [
        (("ingredient_id",), {}),
        (("stock_status",), {}),
    ],
    "recipes": [(("ingredient_id",), {})],
    "stock_movements": [
        (("movement_id",), {"unique": True}),
        (("branch_id",), {}),
        (("ingredient_id",), {}),
    ],
    "source_documents": [
        (("document_id",), {"unique": True}),
        (("checksum",), {}),
    ],
    "document_chunks": [
        (("chunk_id",), {"unique": True}),
        (("document_id",), {}),
    ],
}

# Compound unique indexes for the collections with a composite natural key.
COMPOUND_UNIQUE_INDEXES: dict[str, list[tuple[tuple[str, ...], dict[str, Any]]]] = {
    "inventory_links": [(("menu_id", "branch_id"), {"unique": True})],
    "branch_stock": [(("branch_id", "ingredient_id"), {"unique": True})],
    "recipes": [(("menu_id", "ingredient_id"), {"unique": True})],
    "deal_items": [
        (("deal_id", "menu_id", "variant_id"), {"unique": True}),
    ],
}
