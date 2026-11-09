from __future__ import annotations

from fastapi import APIRouter, Query

from app.backends.postgres.deps import SessionDep
from app.backends.postgres.services.search_service import (
    list_documents,
    search_health,
    semantic_search,
)
from app.schemas.search import (
    DocumentOut,
    SearchHealthResponse,
    SemanticSearchRequest,
    SemanticSearchResponse,
)

router = APIRouter(prefix="/search", tags=["search"])


@router.post("/semantic", response_model=SemanticSearchResponse)
async def post_semantic(
    req: SemanticSearchRequest,
    session: SessionDep,
) -> SemanticSearchResponse:
    results = await semantic_search(
        session, query=req.query, top_k=req.top_k, min_score=req.min_score,
    )
    return SemanticSearchResponse(
        query=req.query, top_k=req.top_k, min_score=req.min_score,
        count=len(results), results=results,
    )


@router.get("/semantic", response_model=SemanticSearchResponse)
async def get_semantic(
    session: SessionDep,
    q: str = Query(..., min_length=1, max_length=2000),
    k: int = Query(8, ge=1, le=50),
    min_score: float = Query(0.0, ge=-1.0, le=1.0),
) -> SemanticSearchResponse:
    results = await semantic_search(session, query=q, top_k=k, min_score=min_score)
    return SemanticSearchResponse(
        query=q, top_k=k, min_score=min_score,
        count=len(results), results=results,
    )


@router.get("/health", response_model=SearchHealthResponse)
async def health(session: SessionDep) -> SearchHealthResponse:
    return SearchHealthResponse(**await search_health(session))


@router.get("/documents", response_model=list[DocumentOut])
async def documents(session: SessionDep) -> list[DocumentOut]:
    rows = await list_documents(session)
    return [DocumentOut(**row) for row in rows]
