"""
AI concierge backed by Groq (OpenAI-compatible chat completions).

The API key lives only in the server environment. The browser talks to this
service, never to Groq directly.

Grounding: every request rebuilds a compact snapshot of the restaurant from
MongoDB (active menu, branches, low stock for the selected branch) and puts it
in the system prompt, so answers are tied to the actual demo data.
"""
from __future__ import annotations

import httpx
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.config import get_settings
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


async def build_context(db: AsyncIOMotorDatabase, branch_id: str | None = None) -> str:
    items = await db.menu_items.find({"catalog_status": "Active"}).sort(
        [("category", 1), ("item_name", 1)]
    ).to_list(length=None)
    branches = await db.branches.find({}).sort("branch_id", 1).to_list(length=None)

    lines: list[str] = ["BRANCHES:"]
    for branch in branches:
        lines.append(
            f"- {branch['branch_id']} | {branch['branch_name']} | "
            f"{branch.get('seats', 0)} seats | "
            f"{branch.get('tables_count', 0)} tables | {branch.get('hours', '')}"
        )

    lines.append("")
    lines.append(
        f"ACTIVE MENU ({len(items)} dishes) — id | name | category | price | "
        "prep min | dietary | allergens:"
    )
    for item in items:
        lines.append(
            f"- {item['menu_id']} | {item['item_name']} | {item['category']} | "
            f"{float(item.get('base_price_pkr') or 0):.0f} PKR | "
            f"{item.get('prep_time_min', 0)} min | "
            f"{item.get('dietary_hint') or '-'} | {item.get('allergen_hint') or '-'}"
        )

    if branch_id:
        stock = await db.branch_stock.find(
            {"branch_id": branch_id, "stock_status": {"$ne": "OK"}}
        ).sort("available", 1).limit(12).to_list(length=None)
        lines.append("")
        if stock:
            lines.append(f"LOW / OUT OF STOCK AT {branch_id}:")
            for row in stock:
                lines.append(
                    f"- {row['ingredient_id']} | {row['ingredient_name']} | "
                    f"{float(row.get('available') or 0):.2f} {row.get('unit', '')} "
                    f"available | {row.get('stock_status', '')}"
                )
        else:
            lines.append(f"STOCK AT {branch_id}: no low-stock lines.")

    return "\n".join(lines)


async def ask_concierge(
    db: AsyncIOMotorDatabase,
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
        branch = await db.branches.find_one({"branch_id": branch_id})
        if branch is None:
            raise AssistantBranchNotFound(f"Unknown branch: {branch_id}")

    context = await build_context(db, branch_id)
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
            response = await client.post(
                f"{settings.groq_base_url}/chat/completions",
                headers=headers,
                json=payload,
            )
    except httpx.TimeoutException as exc:
        raise AssistantTimeout("The concierge took too long to answer. Try again.") from exc
    except httpx.HTTPError as exc:
        raise AssistantUpstream(f"Could not reach the AI provider: {type(exc).__name__}") from exc

    if response.status_code != 200:
        detail = response.text[:240].replace("\n", " ")
        raise AssistantUpstream(f"AI provider returned {response.status_code}: {detail}")

    data = response.json()
    try:
        reply = data["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError, AttributeError) as exc:
        raise AssistantUpstream("AI provider returned an unexpected response.") from exc

    if not reply:
        raise AssistantUpstream("AI provider returned an empty answer.")

    return {"reply": reply, "model": data.get("model", settings.groq_model)}
