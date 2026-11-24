"""
AI concierge backed by the configured LLM provider.

The API key lives only in the server environment. The browser talks to this
service, never to the selected provider directly.

Grounding: every request rebuilds a compact snapshot of the restaurant from
PostgreSQL (active menu, branches, low stock for the selected branch) and puts
it in the system prompt, so answers are tied to the actual demo data.

Scope: ``app.services.guardrails`` rejects off-topic questions before any
network call and supplies the strict system prompt that keeps the concierge
focused on this restaurant.
"""
from __future__ import annotations

import time

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.backends.postgres.models import Branch, BranchStock, ItemAlias, MenuItem
from app.config import get_settings
from app.schemas.assistant import ChatTurn
from app.services.guardrails import (
    SCOPE_REFUSAL,
    SYSTEM_PROMPT,
    GroundingContext,
    build_messages,
    is_in_scope,
    is_reply_in_scope,
    limit_reply_length,
    sanitize_message,
)
from app.services.llm_client import generate_llm_reply
from app.services.llm_errors import (
    LLMConfigurationError,
    LLMProviderError,
    LLMTimeoutError,
)


class AssistantError(Exception):
    status_code = 502


class AssistantUnavailable(AssistantError):
    status_code = 503


class AssistantBranchNotFound(AssistantError):
    status_code = 404


class AssistantTimeout(AssistantError):
    status_code = 504


class AssistantUpstream(AssistantError):
    status_code = 502


async def build_context(
    session: AsyncSession, branch_id: str | None = None
) -> GroundingContext:
    items = (
        await session.execute(
            select(MenuItem)
            .where(MenuItem.catalog_status == "Active")
            .order_by(MenuItem.category, MenuItem.item_name)
        )
    ).scalars().all()
    branches = (
        await session.execute(select(Branch).order_by(Branch.branch_id))
    ).scalars().all()

    lines: list[str] = ["BRANCHES:"]
    for branch in branches:
        lines.append(
            f"- {branch.branch_id} | {branch.branch_name} | {branch.seats} seats | "
            f"{branch.tables_count} tables | {branch.hours}"
        )

    lines.append("")
    lines.append(
        f"ACTIVE MENU ({len(items)} dishes) — id | name | category | price | "
        "prep min | dietary | allergens | description:"
    )
    vocabulary: list[str] = []
    for item in items:
        vocabulary.append(item.item_name)
        lines.append(
            f"- {item.menu_id} | {item.item_name} | {item.category} | "
            f"{float(item.base_price_pkr):.0f} PKR | {item.prep_time_min} min | "
            f"{item.dietary_hint or '-'} | {item.allergen_hint or '-'} | "
            f"{item.description or '-'}"
        )

    if branch_id:
        stock = (
            await session.execute(
                select(BranchStock)
                .where(
                    BranchStock.branch_id == branch_id,
                    BranchStock.stock_status != "OK",
                )
                .order_by(BranchStock.available.asc())
                .limit(12)
            )
        ).scalars().all()
        lines.append("")
        if stock:
            lines.append(f"LOW / OUT OF STOCK AT {branch_id}:")
            for row in stock:
                available = float(row.available or 0)
                lines.append(
                    f"- {row.ingredient_id} | {row.ingredient_name} | "
                    f"{available:.2f} {row.unit} available | {row.stock_status}"
                )
        else:
            lines.append(f"STOCK AT {branch_id}: no low-stock lines.")

    aliases = (await session.execute(select(ItemAlias))).scalars().all()
    vocabulary.extend(alias.customer_phrase for alias in aliases)

    return GroundingContext(text="\n".join(lines), vocabulary=tuple(vocabulary))


async def ask_concierge(
    session: AsyncSession,
    *,
    message: str,
    history: list[ChatTurn],
    branch_id: str | None = None,
) -> dict:
    started = time.perf_counter()

    def with_latency(reply: str, model: str) -> dict:
        elapsed_ms = max(0, round((time.perf_counter() - started) * 1000))
        return {"reply": reply, "model": model, "latency_ms": elapsed_ms}

    settings = get_settings()
    message = sanitize_message(message)

    context = await build_context(session, branch_id)

    # Guardrail first: a refusal needs no provider key and no network call.
    if not message or not is_in_scope(message, context.vocabulary):
        return with_latency(SCOPE_REFUSAL, "scope-guard")

    if branch_id:
        branch = await session.get(Branch, branch_id)
        if branch is None:
            raise AssistantBranchNotFound(f"Unknown branch: {branch_id}")

    messages = build_messages(context, history, message)
    try:
        reply, model = await generate_llm_reply(messages, settings=settings)
    except LLMConfigurationError as exc:
        raise AssistantUnavailable(str(exc)) from exc
    except LLMTimeoutError as exc:
        raise AssistantTimeout("The concierge took too long to answer. Try again.") from exc
    except LLMProviderError as exc:
        raise AssistantUpstream(str(exc)) from exc

    if not is_reply_in_scope(reply, context.vocabulary):
        return with_latency(SCOPE_REFUSAL, "scope-guard")

    reply = limit_reply_length(reply)
    return with_latency(reply, model)


__all__ = ["SYSTEM_PROMPT", "ask_concierge", "build_context"]
