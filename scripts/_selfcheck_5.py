"""
Self-check for Phase 5. Run: python -m uv run python scripts/_selfcheck_5.py
Exits 0 on success, 1 on failure.

Uses SQLAlchemy async engine with the MIGRATION url (direct, non-pooler) to
inspect pg_catalog after migrations. Every check queries the live database.
"""
import asyncio
import sys

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import get_settings

results: list[tuple[str, str, object]] = []


def check(name: str, condition: bool, got: object = None) -> None:
    status = "PASS" if condition else "FAIL"
    results.append((name, status, got))
    suffix = "" if got is None else f"  (got: {got})"
    print(f"{status}  {name}{suffix}")


async def main() -> int:
    raw = get_settings().database_url
    url = raw.replace("-pooler", "")
    engine = create_async_engine(url, poolclass=None, echo=False)

    async with engine.connect() as conn:
        # --- Alembic version ---
        ver = (await conn.execute(text("SELECT version_num FROM alembic_version"))).scalar()
        check("alembic_version is set", ver is not None and len(ver) > 0, ver)

        # --- Extensions ---
        ext_rows = (await conn.execute(text(
            "SELECT extname FROM pg_extension WHERE extname IN ('vector','pg_trgm')"
        ))).scalars().all()
        check("extension 'vector' installed", "vector" in ext_rows, ext_rows)
        check("extension 'pg_trgm' installed", "pg_trgm" in ext_rows, ext_rows)

        # --- 20 tables ---
        expected_tables = sorted([
            "addons", "allergen_guide", "branch_menu", "branch_stock", "branches",
            "categories", "deal_items", "deals", "document_chunks", "ingredients",
            "inventory_links", "item_addons", "item_aliases", "menu_items",
            "recipes", "service_rules", "source_documents", "stock_movements",
            "suppliers", "variants",
        ])
        table_rows = sorted((await conn.execute(text(
            "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
        ))).scalars().all())
        # filter out alembic_version
        table_rows = [t for t in table_rows if t != "alembic_version"]
        check("20 business tables present", table_rows == expected_tables, table_rows)

        # --- document_chunks.embedding is vector(1536) ---
        emb_type = (await conn.execute(text(
            "SELECT format_type(atttypid, atttypmod) FROM pg_attribute "
            "WHERE attrelid = 'document_chunks'::regclass AND attname = 'embedding'"
        ))).scalar()
        check("document_chunks.embedding is vector(1536)",
              emb_type is not None and "vector(1536)" in emb_type, emb_type)

        # --- HNSW index exists ---
        hnsw = (await conn.execute(text(
            "SELECT indexname, indexdef FROM pg_indexes "
            "WHERE tablename = 'document_chunks' "
            "AND indexdef ILIKE '%USING hnsw%'"
        ))).first()
        check("HNSW index on document_chunks.embedding",
              hnsw is not None and "vector_cosine_ops" in hnsw.indexdef,
              hnsw.indexname if hnsw else None)

        # --- GIN trigram index exists ---
        trgm = (await conn.execute(text(
            "SELECT indexname, indexdef FROM pg_indexes "
            "WHERE tablename = 'item_aliases' "
            "AND indexdef ILIKE '%gin_trgm_ops%'"
        ))).first()
        check("GIN trigram index on item_aliases.customer_phrase",
              trgm is not None, trgm.indexname if trgm else None)

        # --- FK count: composite + single across all tables ---
        # We expect these composite FKs: deal_items(3 cols -> 3 tables),
        # item_addons(2), branch_stock(2), inventory_links(2), recipes(2).
        # Total FK constraints (pg_constraint where contype='f') should be >= 21.
        fk_count = (await conn.execute(text(
            "SELECT count(*) FROM pg_constraint WHERE contype = 'f'"
        ))).scalar()
        check("FK constraint count >= 21", (fk_count or 0) >= 21, fk_count)

        # --- Sample FK spot-checks (schema-qualified, exact) ---
        fk_pairs = (await conn.execute(text(
            "SELECT conrelid::regclass::text AS src, "
            "       confrelid::regclass::text AS tgt "
            "FROM pg_constraint WHERE contype = 'f'"
        ))).all()
        fk_set = {(r.src, r.tgt) for r in fk_pairs}
        for src, tgt in [
            ("branch_menu", "branches"),
            ("document_chunks", "source_documents"),
            ("recipes", "menu_items"),
            ("deal_items", "variants"),
        ]:
            check(f"FK {src} -> {tgt}", (src, tgt) in fk_set, (src, tgt))

    await engine.dispose()
    return 0


async def run() -> int:
    try:
        rc = await main()
    except Exception as exc:  # noqa: BLE001
        check("self-check did not raise", False, f"{type(exc).__name__}: {exc}")
        rc = 1

    print()
    print("=" * 60)
    failed = [r for r in results if r[1] == "FAIL"]
    print(f"PHASE 5 SELF-CHECK  —  {len(results) - len(failed)}/{len(results)} passed")
    print("=" * 60)
    if failed:
        print("FAILED CHECKS:")
        for name, _, got in failed:
            print(f"  - {name}  (got: {got})")
        print()
        print("RESULT: NEEDS FIX")
        return 1
    print("SCHEMA LIVE: 20 tables, vector+pg_trgm extensions, HNSW+GIN indexes.")
    print("RESULT: READY FOR PHASE 6 (menu ingestion)")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(run()))
