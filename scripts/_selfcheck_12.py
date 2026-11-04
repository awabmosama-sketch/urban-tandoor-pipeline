"""
Self-check for Phase 12 (semantic search endpoints).

Run: python -m uv run python scripts/_selfcheck_12.py
Exits 0 on success, 1 on failure.

Structural correctness only: FakeEmbedder is deterministic but not
semantically meaningful, so relevance assertions are informational.
"""
from __future__ import annotations

import asyncio
import re
import subprocess
import sys
from pathlib import Path

import httpx
from sqlalchemy import func, select, text

from app.database import async_session_factory, engine
from app.main import app
from app.models import DocumentChunk

ROOT = Path(__file__).resolve().parents[1]

results: list[tuple[str, str, object]] = []

SEARCH_ENDPOINT_KEYS = {
    "search_semantic_post", "search_semantic_get",
    "search_health", "search_documents",
}


def check(name: str, condition: bool, got=None) -> None:
    status = "PASS" if condition else "FAIL"
    results.append((name, status, got))
    print(f"{status}  {name}" + ("" if got is None else f"  (got: {got})"))


def run_pytest() -> tuple[int, str]:
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-q"],
        capture_output=True, text=True, cwd=str(ROOT), timeout=600,
    )
    out = (proc.stdout or "") + (proc.stderr or "")
    m = re.search(r"(\d+) passed", out)
    passed = int(m.group(1)) if m else 0
    return passed, out.strip().splitlines()[-1] if out.strip() else ""


async def jget(client: httpx.AsyncClient, path: str, **params):
    resp = await client.get(path, params=params or None)
    try:
        body = resp.json()
    except Exception:  # noqa: BLE001
        body = None
    return resp, body


async def jpost(client: httpx.AsyncClient, path: str, payload: dict):
    resp = await client.post(path, json=payload)
    try:
        body = resp.json()
    except Exception:  # noqa: BLE001
        body = None
    return resp, body


async def checks(pytest_passed: int, pytest_tail: str) -> None:
    transport = httpx.ASGITransport(app=app)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            # --- GROUP A ---
            async with async_session_factory() as session:
                total = (await session.execute(text("SELECT count(*) FROM document_chunks"))).scalar()
                nulls = (await session.execute(text(
                    "SELECT count(*) FROM document_chunks WHERE embedding IS NULL"
                ))).scalar()
                docs = (await session.execute(text(
                    "SELECT count(DISTINCT document_id) FROM document_chunks"
                ))).scalar()
            check(
                "A1 chunks=128, null embeddings=0, distinct docs=2",
                total == 128 and nulls == 0 and docs == 2,
                (total, nulls, docs),
            )
            check(
                "A2 pytest: 2+ passed, 0 failed",
                pytest_passed >= 2 and "failed" not in pytest_tail,
                pytest_tail,
            )

            # --- GROUP B: search health ---
            r, h = await jget(client, "/api/v1/search/health")
            check("B1 GET /search/health 200", r.status_code == 200, r.status_code)
            check("B2 chunks_total == 128", h.get("chunks_total") == 128, h.get("chunks_total"))
            check(
                "B3 chunks_with_embedding == 128",
                h.get("chunks_with_embedding") == 128,
                h.get("chunks_with_embedding"),
            )
            check(
                "B4 distinct_documents == 2",
                h.get("distinct_documents") == 2,
                h.get("distinct_documents"),
            )
            check("B5 embedding_dim == 1536", h.get("embedding_dim") == 1536, h.get("embedding_dim"))
            check(
                "B6 hnsw_index_present == True",
                h.get("hnsw_index_present") is True,
                h.get("hnsw_index_present"),
            )

            # --- GROUP C: POST structure ---
            r, c1 = await jpost(client, "/api/v1/search/semantic", {"query": "chicken biryani", "top_k": 5})
            check("C1 POST semantic 200", r.status_code == 200, r.status_code)
            check(
                "C2 response has query/top_k/min_score/count/results",
                isinstance(c1, dict)
                and {"query", "top_k", "min_score", "count", "results"} <= set(c1),
                sorted(c1) if isinstance(c1, dict) else None,
            )
            cres = c1.get("results") or []
            check(
                "C3 count == len(results) and <= 5",
                c1.get("count") == len(cres) and len(cres) <= 5,
                (c1.get("count"), len(cres)),
            )
            need = {"chunk_id", "document_id", "content", "token_count", "score"}
            check(
                "C4 every result has required fields",
                bool(cres) and all(need <= set(x) for x in cres),
                "all results" if cres else "no results",
            )
            check(
                "C5 every score is a float in [-1, 1]",
                all(isinstance(x["score"], float) and -1.0 <= x["score"] <= 1.0 for x in cres),
                [x["score"] for x in cres[:3]],
            )
            scores = [x["score"] for x in cres]
            check(
                "C6 results sorted by score DESC",
                all(scores[i] >= scores[i + 1] for i in range(len(scores) - 1)),
                scores,
            )
            ids = [x["chunk_id"] for x in cres]
            async with async_session_factory() as session:
                found = (await session.execute(
                    select(func.count()).select_from(DocumentChunk)
                    .where(DocumentChunk.chunk_id.in_(ids))
                )).scalar() if ids else 0
            check(
                "C7 all chunk_ids exist in DB",
                ids and found == len(ids),
                (found, len(ids)),
            )

            # --- GROUP D: POST validation edge cases ---
            cases = [
                ("D1 empty query -> 422", {"query": ""}),
                ("D2 query 2001 chars -> 422", {"query": "x" * 2001}),
                ("D3 top_k=0 -> 422", {"query": "x", "top_k": 0}),
                ("D4 top_k=51 -> 422", {"query": "x", "top_k": 51}),
                ("D5 min_score=-1.5 -> 422", {"query": "x", "min_score": -1.5}),
                ("D6 min_score=2.0 -> 422", {"query": "x", "min_score": 2.0}),
            ]
            for label, payload in cases:
                rr, _ = await jpost(client, "/api/v1/search/semantic", payload)
                check(label, rr.status_code == 422, rr.status_code)
            r, d7 = await jpost(
                client, "/api/v1/search/semantic",
                {"query": "non-existent-xyz-zzz", "top_k": 3},
            )
            check(
                "D7 unknown query still returns 3 (fake provider)",
                r.status_code == 200 and d7.get("count") == 3,
                (r.status_code, d7.get("count")),
            )

            # --- GROUP E: pagination + min_score ---
            _, e3 = await jpost(client, "/api/v1/search/semantic", {"query": "biryani", "top_k": 3})
            _, e10 = await jpost(client, "/api/v1/search/semantic", {"query": "biryani", "top_k": 10})
            check(
                "E1 top_k bounds respected (3 and 10)",
                len(e3.get("results") or []) <= 3
                and len(e10.get("results") or []) <= 10
                and len(e10.get("results") or []) >= len(e3.get("results") or []),
                (len(e3.get("results") or []), len(e10.get("results") or [])),
            )
            _, base = await jpost(client, "/api/v1/search/semantic", {"query": "biryani", "top_k": 20, "min_score": 0.0})
            _, hi = await jpost(client, "/api/v1/search/semantic", {"query": "biryani", "top_k": 20, "min_score": 0.9})
            check(
                "E2 min_score=0.9 count <= min_score=0.0 count",
                hi.get("count", 0) <= base.get("count", 0),
                (hi.get("count"), base.get("count")),
            )
            _, lo = await jpost(client, "/api/v1/search/semantic", {"query": "biryani", "top_k": 20, "min_score": -1.0})
            check(
                "E4 min_score=-1.0 count == min_score=0.0 count",
                lo.get("count") == base.get("count"),
                (lo.get("count"), base.get("count")),
            )

            # --- GROUP F: GET ---
            r, f1 = await jget(client, "/api/v1/search/semantic", q="chicken biryani", k=5)
            check(
                "F1 GET semantic 200, count <= 5",
                r.status_code == 200 and f1.get("count", 99) <= 5,
                (r.status_code, f1.get("count")),
            )
            _, post_same = await jpost(
                client, "/api/v1/search/semantic",
                {"query": "chicken biryani", "top_k": 5},
            )
            get_ids = [x["chunk_id"] for x in (f1.get("results") or [])[:3]]
            post_ids = [x["chunk_id"] for x in (post_same.get("results") or [])[:3]]
            check(
                "F2 GET vs POST first 3 chunk_ids identical",
                get_ids == post_ids,
                (get_ids, post_ids),
            )
            for label, params in [
                ("F3 empty q -> 422", {"q": ""}),
                ("F4 k=0 -> 422", {"q": "x", "k": 0}),
                ("F5 k=100 -> 422", {"q": "x", "k": 100}),
                ("F6 missing q -> 422", {}),
            ]:
                rr, _ = await jget(client, "/api/v1/search/semantic", **params)
                check(label, rr.status_code == 422, rr.status_code)

            # --- GROUP G: determinism ---
            payload = {"query": "deterministic check", "top_k": 7}
            _, g1a = await jpost(client, "/api/v1/search/semantic", payload)
            _, g1b = await jpost(client, "/api/v1/search/semantic", payload)
            ids_a = [x["chunk_id"] for x in g1a.get("results") or []]
            ids_b = [x["chunk_id"] for x in g1b.get("results") or []]
            sc_a = [x["score"] for x in g1a.get("results") or []]
            sc_b = [x["score"] for x in g1b.get("results") or []]
            check(
                "G1 POST twice identical ids and scores (1e-6)",
                ids_a == ids_b and len(sc_a) == len(sc_b)
                and all(abs(a - b) < 1e-6 for a, b in zip(sc_a, sc_b)),
                (ids_a[:3], sc_a[:3]),
            )
            _, g2 = await jget(client, "/api/v1/search/semantic", q="deterministic check", k=7)
            check(
                "G2 GET and POST identical chunk_ids",
                [x["chunk_id"] for x in g2.get("results") or []] == ids_a,
                [x["chunk_id"] for x in g2.get("results") or []][:3],
            )

            # --- GROUP H: documents ---
            r, docs = await jget(client, "/api/v1/search/documents")
            check("H1 GET /search/documents 200, length 2", r.status_code == 200 and len(docs or []) == 2, (r.status_code, len(docs or [])))
            dmap = {d["document_id"]: d for d in docs or []}
            prof = dmap.get("docx:urban_tandoor_profile", {})
            menu = dmap.get("menu:catalog_narratives", {})
            check("H2 profile chunk_count == 10", prof.get("chunk_count") == 10, prof.get("chunk_count"))
            check("H3 menu chunk_count == 118", menu.get("chunk_count") == 118, menu.get("chunk_count"))
            need_doc = {"document_id", "source_path", "source_type", "title", "checksum", "loaded_at", "chunk_count"}
            check(
                "H4 every document has required fields",
                bool(docs) and all(need_doc <= set(d) for d in docs),
                "all documents" if docs else "none",
            )
            check("H5 profile source_type == docx", prof.get("source_type") == "docx", prof.get("source_type"))
            check("H6 menu source_type == xlsx_sheet", menu.get("source_type") == "xlsx_sheet", menu.get("source_type"))

            # --- GROUP I: content fidelity ---
            _, i1 = await jpost(client, "/api/v1/search/semantic", {"query": "chicken biryani", "top_k": 1})
            first = (i1.get("results") or [{}])[0]
            async with async_session_factory() as session:
                db_content = (await session.execute(
                    select(DocumentChunk.content).where(DocumentChunk.chunk_id == first.get("chunk_id"))
                )).scalar()
            check(
                "I1 API content == DB content for first result",
                bool(first) and db_content == first.get("content"),
                first.get("chunk_id"),
            )
            async with async_session_factory() as session:
                menu1 = (await session.execute(
                    select(func.count()).select_from(DocumentChunk)
                    .where(
                        DocumentChunk.document_id == "menu:catalog_narratives",
                        DocumentChunk.content.like("MENU001 %"),
                    )
                )).scalar()
            check("I2 exactly 1 MENU001 narrative chunk", menu1 == 1, menu1)
            _, i3 = await jpost(
                client, "/api/v1/search/semantic",
                {"query": "MENU001 Chicken Biryani 420", "top_k": 20},
            )
            hit = any("MENU001" in (x.get("content") or "") for x in i3.get("results") or [])
            check(
                "I3 MENU001 appears in top-20 (informational)",
                True,
                "present" if hit else "skipped: fake embeddings don't guarantee relevance",
            )

            # --- GROUP J: OpenAPI ---
            r, spec = await jget(client, "/openapi.json")
            paths = (spec or {}).get("paths", {})
            sem = paths.get("/api/v1/search/semantic", {})
            check(
                "J1 openapi /search/semantic has GET+POST",
                "get" in sem and "post" in sem,
                sorted(sem),
            )
            check(
                "J2 openapi contains /search/health",
                "/api/v1/search/health" in paths,
                None,
            )
            check(
                "J3 openapi contains /search/documents",
                "/api/v1/search/documents" in paths,
                None,
            )
            schemas = set((spec or {}).get("components", {}).get("schemas", {}))
            need_schemas = {
                "SemanticSearchRequest", "SemanticSearchResponse",
                "ChunkResult", "SearchHealthResponse", "DocumentOut",
            }
            check(
                "J4 openapi schemas include all search DTOs",
                need_schemas <= schemas,
                sorted(need_schemas - schemas) or "all present",
            )

            # --- GROUP K: regression ---
            check(
                "K1 pytest: N passed, 0 failed",
                pytest_passed >= 2 and "failed" not in pytest_tail,
                pytest_tail,
            )
            r, health = await jget(client, "/health")
            check(
                "K2 /health 200, db=ok",
                r.status_code == 200 and health.get("db") == "ok",
                (r.status_code, health.get("db")),
            )
            r, avail = await jget(
                client, "/api/v1/inventory/availability/MENU001",
                branch_id="UTG-KHI-001",
            )
            check(
                "K3 MENU001@001 max_portions == 142",
                r.status_code == 200 and avail.get("max_portions") == 142,
                (r.status_code, avail.get("max_portions")),
            )
            r, items = await jget(client, "/api/v1/menu/items")
            check(
                "K4 /menu/items == 32 active items",
                r.status_code == 200 and len(items or []) == 32,
                len(items or []),
            )
            r, root = await jget(client, "/api/v1/")
            endpoints = (root or {}).get("endpoints") or {}
            check(
                "K5 api_root has all 4 search keys",
                SEARCH_ENDPOINT_KEYS <= set(endpoints),
                sorted(SEARCH_ENDPOINT_KEYS - set(endpoints)) or "all present",
            )
    finally:
        await engine.dispose()


def main() -> int:
    pytest_passed, pytest_tail = run_pytest()
    asyncio.run(checks(pytest_passed, pytest_tail))

    print()
    print("=" * 60)
    failed = [r for r in results if r[1] == "FAIL"]
    print(f"PHASE 12 SELF-CHECK — {len(results) - len(failed)}/{len(results)} passed")
    print("=" * 60)
    if failed:
        print("FAILED CHECKS:")
        for name, _, got in failed:
            print(f"  - {name}  (got: {got})")
        print()
        return 1
    print("SEMANTIC SEARCH VERIFIED: health, POST/GET, validation, determinism, documents.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
