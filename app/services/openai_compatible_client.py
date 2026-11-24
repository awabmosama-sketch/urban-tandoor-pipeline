"""Async client for OpenAI-compatible chat-completion APIs."""
from __future__ import annotations

import logging

import httpx

from app.services.llm_errors import (
    LLMProviderError,
    LLMTimeoutError,
    redact_secrets,
)

logger = logging.getLogger(__name__)


async def generate_openai_compatible_reply(
    messages: list[dict[str, str]],
    *,
    provider: str,
    api_key: str,
    model: str,
    base_url: str,
    timeout_s: float,
) -> tuple[str, str]:
    url = f"{base_url.rstrip('/')}/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=timeout_s) as client:
            response = await client.post(
                url,
                headers=headers,
                json={
                    "model": model,
                    "messages": messages,
                    "temperature": 0.35,
                    "max_tokens": 192,
                },
            )
    except httpx.TimeoutException as exc:
        raise LLMTimeoutError from exc
    except httpx.HTTPError as exc:
        raise LLMProviderError(
            f"Could not reach {provider}: {type(exc).__name__}"
        ) from exc

    if response.status_code != 200:
        try:
            error_data = response.json()
        except ValueError:
            error_data = None
        error = error_data.get("error") if isinstance(error_data, dict) else None
        detail = error.get("message") if isinstance(error, dict) else None
        if isinstance(detail, str) and detail:
            logger.warning(
                "%s HTTP %s: %s",
                provider,
                response.status_code,
                redact_secrets(detail, api_key)[:1000],
            )
        message = (
            f"{provider} returned HTTP {response.status_code}. Check server logs."
        )
        raise LLMProviderError(message)

    try:
        data = response.json()
    except ValueError as exc:
        raise LLMProviderError(f"{provider} returned invalid JSON.") from exc

    choices = data.get("choices") if isinstance(data, dict) else None
    choice = choices[0] if isinstance(choices, list) and choices else None
    message = choice.get("message") if isinstance(choice, dict) else None
    reply = message.get("content") if isinstance(message, dict) else None
    if not isinstance(reply, str) or not reply.strip():
        raise LLMProviderError(f"{provider} returned an unexpected or empty response.")

    response_model = data.get("model")
    return reply.strip(), (
        response_model
        if isinstance(response_model, str) and response_model.strip()
        else model
    )
