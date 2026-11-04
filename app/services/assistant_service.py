"""
AI concierge backed by Groq (OpenAI-compatible chat completions).

The API key lives only in the server environment. The browser talks to this
service, never to Groq directly.

Grounding: every request rebuilds a compact snapshot of the restaurant from
Postgres (active menu, branches, low stock for the selected branch) and puts
it in the system prompt, so answers are tied to the actual demo data.
"""
from __future__ import annotations

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import Branch, BranchStock, MenuItem
from app.schemas.assistant import ChatTurn

SYSTEM_PROMPT = """You are the concierge for Urban Tandoor & Grill, a Pakistani \
grill restaurant in Karachi with two 24/7 branches. All data is synthetic demo data.

Rules:
- Answer in at most 120 words, warm and precise. Use short lines.
- Do not use markdown, asterisks, bold, headings or tables. Hyphen lines are fine.
- Use ONLY the RESTAURANT DATA below for menu items, prices, branches, stock and
  availability. If a fact is absent, say you do not have it. Never invent dishes,
  prices, discounts or promises.
- Prices are PKR. Availability is a live estimate derived from recipes and branch
  stock, not a reservation.
- Speak like a knowledgeable host, not a chatbot. No markdown tables.
"""


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


async def build_context(session: AsyncSession, branch_id: str | None = None) -> str:
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

    lines: list[str] = [
        "BRANCHES:",
    ]
    for b in branches:
        lines.append(
            f"- {b.branch_id} | {b.branch_name} | {b.seats} seats | "
            f"{b.tables_count} tables | {b.hours}"
        )

    lines.append("")
    lines.append(
        f"ACTIVE MENU ({len(items)} dishes) — id | name | category | price | "
        "prep min | dietary | allergens:"
    )
    for m in items:
        lines.append(
            f"- {m.menu_id} | {m.item_name} | {m.category} | "
            f"{float(m.base_price_pkr):.0f} PKR | {m.prep_time_min} min | "
            f"{m.dietary_hint or '-'} | {m.allergen_hint or '-'}"
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
            for s in stock:
                lines.append(
                    f"- {s.ingredient_id} | {s.ingredient_name} | "
                    f"{s.available:.2f} {s.unit} available | {s.stock_status}"
                )
        else:
            lines.append(f"STOCK AT {branch_id}: no low-stock lines.")

    return "\n".join(lines)


async def ask_concierge(
    session: AsyncSession,
    *,
    message: str,
    history: list[ChatTurn],
    branch_id: str | None = None,
) -> dict:
    settings = get_settings()
    if not settings.groq_api_key:
        raise AssistantUnavailable(
            "AI concierge is not configured yet (GROQ_API_KEY is missing)."
        )

    if branch_id:
        branch = await session.get(Branch, branch_id)
        if branch is None:
            raise AssistantBranchNotFound(f"Unknown branch: {branch_id}")

    context = await build_context(session, branch_id)
    messages: list[dict] = [
        {"role": "system", "content": f"{SYSTEM_PROMPT}\n\nRESTAURANT DATA:\n{context}"}
    ]
    for turn in history[-8:]:
        messages.append({"role": turn.role, "content": turn.content})
    messages.append({"role": "user", "content": message})

    payload = {
        "model": settings.groq_model,
        "messages": messages,
        "temperature": 0.35,
        "max_tokens": 450,
        "top_p": 0.9,
    }
    headers = {
        "Authorization": f"Bearer {settings.groq_api_key}",
        "Content-Type": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=settings.groq_timeout_s) as client:
            resp = await client.post(
                f"{settings.groq_base_url}/chat/completions",
                headers=headers,
                json=payload,
            )
    except httpx.TimeoutException as exc:
        raise AssistantTimeout("The concierge took too long to answer. Try again.") from exc
    except httpx.HTTPError as exc:
        raise AssistantUpstream(f"Could not reach the AI provider: {type(exc).__name__}") from exc

    if resp.status_code != 200:
        detail = resp.text[:240].replace("\n", " ")
        raise AssistantUpstream(f"AI provider returned {resp.status_code}: {detail}")

    data = resp.json()
    try:
        reply = data["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError, AttributeError) as exc:
        raise AssistantUpstream("AI provider returned an unexpected response.") from exc

    if not reply:
        raise AssistantUpstream("AI provider returned an empty answer.")

    return {"reply": reply, "model": data.get("model", settings.groq_model)}
