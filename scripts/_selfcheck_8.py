"""
Self-check for Phase 8. Run: python -m uv run python scripts/_selfcheck_8.py
Exits 0 on success, 1 on failure.
"""
import asyncio
import json
import math
import subprocess
import sys
from pathlib import Path

from sqlalchemy import text

from app.config import get_settings
from app.database import async_session_factory
from app.ingestion.docs_pipeline import ingest_all_docs

results: list[tuple[str, str, object]] = []


def check(name, condition, got=None):
    status = "PASS" if condition else "FAIL"
    results.append((name, status, got))
    print(f"{status}  {name}" + ("" if got is None else f"  (got: {got})"))


async def fetch_count(session, table: str) -> int:
    return (await session.execute(text(f"SELECT count(*) FROM {table}"))).scalar()


async def fetch_one(session, sql: str, **kw):
    return (await session.execute(text(sql), kw)).mappings().first()


async def run_ingest() -> dict:
    async with async_session_factory() as session:
        r = await ingest_all_docs(session)
        await session.commit()
    return r


async def main() -> int:
    settings = get_settings()

    # Phase 8 is a fresh initialization of the document tables; clear any
    # previous run so GROUP A's "fresh state" assertion is meaningful and
    # the whole self-check can be re-run safely.
    async with async_session_factory() as session:
        await session.execute(text("DELETE FROM document_chunks"))
        await session.execute(text("DELETE FROM source_documents"))
        await session.commit()

    # --- GROUP A: setup ---
    path = Path(settings.data_dir) / "Urban_Tandoor_Grill_Restaurant_Profile.docx"
    check("profile DOCX present", path.exists(), path.name)

    async with async_session_factory() as session:
        menu_items = await fetch_count(session, "menu_items")
        categories = await fetch_count(session, "categories")
        sd = await fetch_count(session, "source_documents")
        dc = await fetch_count(session, "document_chunks")
    check("Phase 6 baseline: menu_items == 118", menu_items == 118, menu_items)
    check("Phase 6 baseline: categories == 8", categories == 8, categories)
    check("fresh: source_documents == 0", sd == 0, sd)
    check("fresh: document_chunks == 0", dc == 0, dc)

    # --- GROUP B: pass 1 ---
    r1 = await run_ingest()
    check(
        "pass 1 profile.status == 'ingested'",
        r1["profile"]["status"] == "ingested",
        r1["profile"]["status"],
    )
    check(
        "pass 1 menu_narratives.status == 'ingested'",
        r1["menu_narratives"]["status"] == "ingested",
        r1["menu_narratives"]["status"],
    )

    async with async_session_factory() as session:
        sd_count = await fetch_count(session, "source_documents")
        dc_count = await fetch_count(session, "document_chunks")
        profile_chunks = (await session.execute(text(
            "SELECT count(*) FROM document_chunks "
            "WHERE document_id = 'docx:urban_tandoor_profile'"
        ))).scalar()
        menu_chunks = (await session.execute(text(
            "SELECT count(*) FROM document_chunks "
            "WHERE document_id = 'menu:catalog_narratives'"
        ))).scalar()
    check("source_documents count == 2", sd_count == 2, sd_count)
    check("document_chunks count >= 120", dc_count >= 120, dc_count)
    check("profile chunks > 0", profile_chunks > 0, profile_chunks)
    check("menu narrative chunks == 118", menu_chunks == 118, menu_chunks)

    # --- GROUP C: embeddings valid ---
    async with async_session_factory() as session:
        null_emb = (await session.execute(text(
            "SELECT count(*) FROM document_chunks WHERE embedding IS NULL"
        ))).scalar()
        check("no NULL embeddings", null_emb == 0, null_emb)

        bad_tokens = (await session.execute(text(
            "SELECT count(*) FROM document_chunks WHERE token_count <= 0"
        ))).scalar()
        check("no token_count <= 0", bad_tokens == 0, bad_tokens)

        bad_content = (await session.execute(text(
            "SELECT count(*) FROM document_chunks "
            "WHERE content = '' OR content IS NULL"
        ))).scalar()
        check("no empty content", bad_content == 0, bad_content)

        emb_rows = (await session.execute(text(
            "SELECT chunk_id, embedding::text AS emb FROM document_chunks"
        ))).mappings().all()
        norm_violations = 0
        for row in emb_rows:
            vec = json.loads(row["emb"])
            norm = math.sqrt(sum(float(x) * float(x) for x in vec))
            if abs(norm - 1.0) >= 0.02:
                norm_violations += 1
        check(
            f"all embeddings unit-norm ({len(emb_rows)} rows)",
            norm_violations == 0,
            norm_violations,
        )

        missing_section = (await session.execute(text(
            "SELECT count(*) FROM document_chunks "
            "WHERE NOT jsonb_exists(metadata_json, 'section')"
        ))).scalar()
        check(
            "every chunk metadata_json has 'section' key",
            missing_section == 0,
            missing_section,
        )

        # --- GROUP D: menu narrative spot checks ---
        men001 = (await session.execute(text(
            "SELECT count(*) FROM document_chunks "
            "WHERE document_id = 'menu:catalog_narratives' "
            "AND content LIKE 'MENU001 %'"
        ))).scalar()
        check("MENU001 narrative exists exactly once", men001 == 1, men001)

        men033 = (await session.execute(text(
            "SELECT count(*) FROM document_chunks "
            "WHERE document_id = 'menu:catalog_narratives' "
            "AND content LIKE 'MENU033 %'"
        ))).scalar()
        check("MENU033 narrative exists exactly once", men033 == 1, men033)

        not_menu = (await session.execute(text(
            "SELECT count(*) FROM document_chunks "
            "WHERE document_id = 'menu:catalog_narratives' "
            "AND content NOT LIKE 'MENU%'"
        ))).scalar()
        check("all menu narratives start with MENU###", not_menu == 0, not_menu)

        content = (await session.execute(text(
            "SELECT content FROM document_chunks "
            "WHERE document_id = 'menu:catalog_narratives' "
            "AND content LIKE 'MENU001 %'"
        ))).scalar()
        check(
            "MENU001 narrative contains 'Chicken Biryani' and '420'",
            bool(content) and "Chicken Biryani" in content and "420" in content,
            content[:80] if content else None,
        )

        # --- GROUP E: DOCX narrative spot checks ---
        profile_sections = set((await session.execute(text(
            "SELECT DISTINCT section FROM document_chunks "
            "WHERE document_id = 'docx:urban_tandoor_profile'"
        ))).scalars().all())
        keywords = [
            "overview", "branches", "food", "ordering", "reservation",
            "payment", "inventory", "customer", "quick",
        ]
        has_heading = any(
            any(k in (s or "").lower() for k in keywords)
            for s in profile_sections
        )
        check(
            "profile has an expected heading section",
            has_heading,
            sorted(s for s in profile_sections if s),
        )

        mentions = (await session.execute(text(
            "SELECT count(*) FROM document_chunks "
            "WHERE document_id = 'docx:urban_tandoor_profile' "
            "AND (lower(content) LIKE '%branches%' OR content LIKE '%24%')"
        ))).scalar()
        check(
            "profile mentions 24/24-7 or branches",
            mentions > 0,
            mentions,
        )

        non_null_section = (await session.execute(text(
            "SELECT count(*) FROM document_chunks "
            "WHERE document_id = 'docx:urban_tandoor_profile' "
            "AND section IS NOT NULL"
        ))).scalar()
        check(
            "profile has chunks with non-NULL section",
            non_null_section > 0,
            non_null_section,
        )

    # --- GROUP F: idempotency ---
    async with async_session_factory() as session:
        checksums_before = dict((await session.execute(text(
            "SELECT document_id, checksum FROM source_documents"
        ))).all())

    r2 = await run_ingest()
    check(
        "pass 2 profile.status == 'skipped'",
        r2["profile"]["status"] == "skipped",
        r2["profile"]["status"],
    )
    check(
        "pass 2 menu_narratives.status == 'skipped'",
        r2["menu_narratives"]["status"] == "skipped",
        r2["menu_narratives"]["status"],
    )

    async with async_session_factory() as session:
        sd_after = await fetch_count(session, "source_documents")
        dc_after = await fetch_count(session, "document_chunks")
        checksums_after = dict((await session.execute(text(
            "SELECT document_id, checksum FROM source_documents"
        ))).all())
    check("pass 2 source_documents still 2", sd_after == 2, sd_after)
    check("pass 2 document_chunks unchanged", dc_after == dc_count, dc_after)
    check(
        "pass 2 checksums unchanged",
        checksums_before == checksums_after,
        checksums_after,
    )

    # --- GROUP G: incremental update simulation ---
    async with async_session_factory() as session:
        orig_prep = (await session.execute(text(
            "SELECT prep_time_min FROM menu_items WHERE menu_id = 'MENU001'"
        ))).scalar()
    new_prep = int(orig_prep) + 1

    async with async_session_factory() as session:
        await session.execute(text(
            "UPDATE menu_items SET prep_time_min = :v WHERE menu_id = 'MENU001'"
        ), {"v": new_prep})
        await session.commit()

    try:
        r3 = await run_ingest()
        check(
            "pass 3 menu_narratives.status == 'ingested' after prep change",
            r3["menu_narratives"]["status"] == "ingested",
            r3["menu_narratives"]["status"],
        )
        async with async_session_factory() as session:
            menu_chunks_3 = (await session.execute(text(
                "SELECT count(*) FROM document_chunks "
                "WHERE document_id = 'menu:catalog_narratives'"
            ))).scalar()
            content3 = (await session.execute(text(
                "SELECT content FROM document_chunks "
                "WHERE document_id = 'menu:catalog_narratives' "
                "AND content LIKE 'MENU001 %'"
            ))).scalar()
        check("pass 3 menu chunks still 118", menu_chunks_3 == 118, menu_chunks_3)
        check(
            f"pass 3 MENU001 narrative has prep_time {new_prep}",
            bool(content3) and f"Preparation time {new_prep} minutes." in content3,
            content3[:120] if content3 else None,
        )
    finally:
        async with async_session_factory() as session:
            await session.execute(text(
                "UPDATE menu_items SET prep_time_min = :v WHERE menu_id = 'MENU001'"
            ), {"v": orig_prep})
            await session.commit()

    r4 = await run_ingest()
    check(
        "pass 4 menu_narratives.status == 'ingested' after revert",
        r4["menu_narratives"]["status"] == "ingested",
        r4["menu_narratives"]["status"],
    )
    async with async_session_factory() as session:
        menu_chunks_4 = (await session.execute(text(
            "SELECT count(*) FROM document_chunks "
            "WHERE document_id = 'menu:catalog_narratives'"
        ))).scalar()
        content4 = (await session.execute(text(
            "SELECT content FROM document_chunks "
            "WHERE document_id = 'menu:catalog_narratives' "
            "AND content LIKE 'MENU001 %'"
        ))).scalar()
    check("pass 4 menu chunks still 118", menu_chunks_4 == 118, menu_chunks_4)
    check(
        f"pass 4 MENU001 narrative reverted to prep_time {orig_prep}",
        bool(content4) and f"Preparation time {orig_prep} minutes." in content4,
        content4[:120] if content4 else None,
    )

    # --- GROUP H: pytest ---
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-q"],
        capture_output=True, text=True, cwd=str(Path.cwd()),
    )
    out = (proc.stdout or "") + (proc.stderr or "")
    check(
        "pytest reports 2 passed",
        "2 passed" in out and proc.returncode == 0,
        out.strip().splitlines()[-1] if out.strip() else None,
    )

    print()
    print("=" * 60)
    failed = [r for r in results if r[1] == "FAIL"]
    print(f"PHASE 8 SELF-CHECK — {len(results) - len(failed)}/{len(results)} passed")
    print("=" * 60)
    if failed:
        print("FAILED CHECKS:")
        for name, _, got in failed:
            print(f"  - {name}  (got: {got})")
        print()
        return 1
    print("DOCX + MENU NARRATIVES INGESTED: embeddings, idempotency, incremental refresh verified.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
