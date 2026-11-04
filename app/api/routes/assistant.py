from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.api.deps import SessionDep
from app.schemas.assistant import AssistantRequest, AssistantResponse
from app.services.assistant_service import (
    AssistantBranchNotFound,
    AssistantError,
    AssistantUnavailable,
    ask_concierge,
)

router = APIRouter(prefix="/assistant", tags=["assistant"])


@router.post("/chat", response_model=AssistantResponse)
async def chat(req: AssistantRequest, session: SessionDep) -> AssistantResponse:
    """Grounded restaurant chat. The Groq key stays server-side."""
    try:
        out = await ask_concierge(
            session,
            message=req.message,
            history=req.history,
            branch_id=req.branch_id,
        )
    except AssistantBranchNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except AssistantUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except AssistantError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return AssistantResponse(**out)
