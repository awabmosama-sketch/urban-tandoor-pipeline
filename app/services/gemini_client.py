"""Small async client for Gemini content generation."""
from __future__ import annotations

import logging
from urllib.parse import quote

import httpx

from app.services.llm_errors import (
    LLMProviderError,
    LLMTimeoutError,
    redact_secrets,
)

logger = logging.getLogger(__name__)


class GeminiTimeoutError(LLMTimeoutError):
    """Gemini did not respond before the configured timeout."""


class GeminiProviderError(LLMProviderError):
    """Gemini returned an error or an unexpected response."""


async def generate_gemini_reply(
    messages: list[dict[str, str]],
    *,
    api_key: str,
    model: str,
    base_url: str,
    timeout_s: float,
) -> tuple[str, str]:
    """Send the concierge prompt to Gemini and return text and model version."""
    contents: list[dict] = []
    for message in messages[1:]:
        role = "model" if message["role"] == "assistant" else "user"
        text = message["content"]
        if contents and contents[-1]["role"] == role:
            contents[-1]["parts"][0]["text"] += "\n\n" + text
        else:
            contents.append({"role": role, "parts": [{"text": text}]})

    payload = {
        "systemInstruction": {"parts": [{"text": messages[0]["content"]}]},
        "contents": contents,
        "generationConfig": {
            "temperature": 0.35,
            "maxOutputTokens": 96,
            "topP": 0.9,
        },
    }
    url = f"{base_url.rstrip('/')}/models/{quote(model, safe='')}:generateContent"
    headers = {"x-goog-api-key": api_key, "Content-Type": "application/json"}

    try:
        async with httpx.AsyncClient(timeout=timeout_s) as client:
            response = await client.post(url, headers=headers, json=payload)
    except httpx.TimeoutException as exc:
        raise GeminiTimeoutError from exc
    except httpx.HTTPError as exc:
        raise GeminiProviderError(
            f"Could not reach Gemini: {type(exc).__name__}"
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
                "Gemini HTTP %s: %s",
                response.status_code,
                redact_secrets(detail, api_key)[:1000],
            )
        message = f"Gemini returned HTTP {response.status_code}. Check server logs."
        raise GeminiProviderError(message)

    try:
        data = response.json()
    except ValueError as exc:
        raise GeminiProviderError("Gemini returned invalid JSON.") from exc

    candidates = data.get("candidates") if isinstance(data, dict) else None
    candidate = candidates[0] if isinstance(candidates, list) and candidates else None
    content = candidate.get("content") if isinstance(candidate, dict) else None
    parts = content.get("parts") if isinstance(content, dict) else None
    if not isinstance(parts, list):
        raise GeminiProviderError("Gemini returned an unexpected response.")

    reply = "".join(
        part["text"]
        for part in parts
        if isinstance(part, dict)
        and isinstance(part.get("text"), str)
        and not part.get("thought")
    ).strip()
    if not reply:
        raise GeminiProviderError("Gemini returned an empty answer.")

    model_version = data.get("modelVersion")
    return (
        reply,
        model_version
        if isinstance(model_version, str) and model_version.strip()
        else model,
    )
