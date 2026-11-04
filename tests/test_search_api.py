"""
Phase 12 semantic search endpoints.
Fake embeddings → structural correctness matters, not relevance.
"""
import pytest


@pytest.mark.asyncio
async def test_search_health(client):
    r = await client.get("/api/v1/search/health")
    assert r.status_code == 200
    h = r.json()
    assert h["chunks_total"] == 128
    assert h["chunks_with_embedding"] == 128
    assert h["distinct_documents"] == 2
    assert h["embedding_dim"] == 1536
    assert h["hnsw_index_present"] is True


@pytest.mark.asyncio
async def test_search_semantic_post(client):
    r = await client.post(
        "/api/v1/search/semantic",
        json={"query": "chicken biryani", "top_k": 5},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == len(body["results"]) <= 5
    assert body["query"] == "chicken biryani"
    # Scores must be sorted DESC
    scores = [r["score"] for r in body["results"]]
    assert scores == sorted(scores, reverse=True)


@pytest.mark.asyncio
async def test_search_validation(client):
    # Empty query
    r = await client.post("/api/v1/search/semantic", json={"query": ""})
    assert r.status_code == 422
    # top_k out of range
    r = await client.post("/api/v1/search/semantic",
                          json={"query": "x", "top_k": 100})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_search_get_matches_post(client):
    post = await client.post(
        "/api/v1/search/semantic",
        json={"query": "biryani", "top_k": 3},
    )
    get = await client.get("/api/v1/search/semantic?q=biryani&k=3")
    assert post.status_code == get.status_code == 200
    post_ids = [r["chunk_id"] for r in post.json()["results"]]
    get_ids = [r["chunk_id"] for r in get.json()["results"]]
    assert post_ids == get_ids


@pytest.mark.asyncio
async def test_search_deterministic(client):
    """Same query → same results (fake embeddings are deterministic)."""
    r1 = await client.post("/api/v1/search/semantic",
                           json={"query": "chicken karahi", "top_k": 5})
    r2 = await client.post("/api/v1/search/semantic",
                           json={"query": "chicken karahi", "top_k": 5})
    assert r1.json()["results"] == r2.json()["results"]


@pytest.mark.asyncio
async def test_documents_list(client):
    r = await client.get("/api/v1/search/documents")
    assert r.status_code == 200
    docs = r.json()
    assert len(docs) == 2
    by_id = {d["document_id"]: d for d in docs}
    assert by_id["docx:urban_tandoor_profile"]["chunk_count"] == 10
    assert by_id["menu:catalog_narratives"]["chunk_count"] == 118
    assert by_id["docx:urban_tandoor_profile"]["source_type"] == "docx"
