from __future__ import annotations
from fastapi import APIRouter
from app.api.routes import health, menu, inventory, search, admin, assistant

api_router = APIRouter(prefix="/api/v1")


@api_router.get("/", tags=["root"])
async def api_root() -> dict:
    from app.api.routes.health import _version
    return {
        "service": "Urban Tandoor & Grill — Menu & Inventory API",
        "version": _version(),
        "docs": "/docs",
        "openapi": "/openapi.json",
        "endpoints": {
            "health_top": "/health",
            "health_v1": "/api/v1/",
            "menu_categories": "/api/v1/menu/categories",
            "menu_items": "/api/v1/menu/items",
            "menu_item_detail": "/api/v1/menu/items/{menu_id}",
            "menu_item_variants": "/api/v1/menu/items/{menu_id}/variants",
            "menu_item_addons": "/api/v1/menu/items/{menu_id}/addons",
            "menu_aliases": "/api/v1/menu/aliases",
            "inventory_branches": "/api/v1/inventory/branches",
            "inventory_stock": "/api/v1/inventory/branches/{branch_id}/stock",
            "inventory_stock_detail":
                "/api/v1/inventory/branches/{branch_id}/stock/{ingredient_id}",
            "availability_single":
                "/api/v1/inventory/availability/{menu_id}",
            "availability_bulk":
                "/api/v1/inventory/branches/{branch_id}/availability",
            "search_semantic_post": "/api/v1/search/semantic",
            "search_semantic_get":  "/api/v1/search/semantic?q=...",
            "search_health":        "/api/v1/search/health",
            "search_documents":     "/api/v1/search/documents",
            "admin_refresh":        "/api/v1/admin/refresh/{domain}",
            "admin_job_detail":     "/api/v1/admin/jobs/{job_id}",
            "admin_jobs_list":      "/api/v1/admin/jobs",
            "assistant_chat":       "/api/v1/assistant/chat",
        },
    }


api_router.include_router(health.router)
api_router.include_router(menu.router)
api_router.include_router(inventory.router)
api_router.include_router(search.router)
api_router.include_router(admin.router)
api_router.include_router(assistant.router)
