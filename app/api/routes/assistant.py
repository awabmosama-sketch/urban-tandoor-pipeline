from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.api.deps import DatabaseDep
from app.config import get_settings
from app.schemas.assistant import (
    AssistantProviderInfo,
    AssistantRequest,
    AssistantResponse,
)
from app.services.assistant_service import (
    AssistantBranchNotFound,
    AssistantError,
    AssistantUnavailable,
    ask_concierge,
)
from app.services.llm_client import get_provider_presentation

router = APIRouter(prefix="/assistant", tags=["assistant"])


@router.get("/provider", response_model=AssistantProviderInfo)
async def provider_info() -> AssistantProviderInfo:
    """Return the selected concierge provider and model, never its credentials."""
    return AssistantProviderInfo(**get_provider_presentation(get_settings()))


@router.post("/chat", response_model=AssistantResponse)
async def chat(req: AssistantRequest, db: DatabaseDep) -> AssistantResponse:
    """Grounded restaurant chat. Provider credentials stay server-side."""
    try:
        output = await ask_concierge(
            db,
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
    return AssistantResponse(**output)
