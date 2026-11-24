"""Provider selection and dispatch for the AI concierge."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from app.config import Settings
from app.services.gemini_client import generate_gemini_reply
from app.services.llm_errors import LLMConfigurationError
from app.services.openai_compatible_client import generate_openai_compatible_reply

Provider = Literal["gemini", "groq", "openai"]


@dataclass(frozen=True)
class ProviderConfig:
    provider: Provider
    label: str
    model: str
    api_key: str
    base_url: str
    api_key_name: str


def get_provider_config(settings: Settings) -> ProviderConfig:
    provider = settings.llm_provider.strip().lower()
    configs: dict[str, ProviderConfig] = {
        "gemini": ProviderConfig(
            provider="gemini",
            label="Gemini",
            model=settings.gemini_model,
            api_key=settings.gemini_api_key,
            base_url=settings.gemini_base_url,
            api_key_name="GEMINI_API_KEY",
        ),
        "groq": ProviderConfig(
            provider="groq",
            label="Groq",
            model=settings.groq_model,
            api_key=settings.groq_api_key,
            base_url=settings.groq_base_url,
            api_key_name="GROQ_API_KEY",
        ),
        "openai": ProviderConfig(
            provider="openai",
            label="OpenAI",
            model=settings.openai_model,
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url,
            api_key_name="OPENAI_API_KEY",
        ),
    }
    if provider not in configs:
        raise LLMConfigurationError(f"Unknown LLM provider {settings.llm_provider!r}")
    return configs[provider]


def get_provider_presentation(settings: Settings) -> dict[str, str]:
    config = get_provider_config(settings)
    return {"provider": config.provider, "model": config.model}


async def generate_llm_reply(
    messages: list[dict[str, str]],
    *,
    settings: Settings,
) -> tuple[str, str]:
    config = get_provider_config(settings)
    if not config.api_key:
        raise LLMConfigurationError(
            f"AI concierge is not configured yet ({config.api_key_name} is missing)."
        )
    if not config.model.strip():
        raise LLMConfigurationError(
            f"AI concierge is not configured ({config.provider.upper()} model is empty)."
        )

    if config.provider == "gemini":
        return await generate_gemini_reply(
            messages,
            api_key=config.api_key,
            model=config.model,
            base_url=config.base_url,
            timeout_s=settings.gemini_timeout_s,
        )

    return await generate_openai_compatible_reply(
        messages,
        provider=config.label,
        api_key=config.api_key,
        model=config.model,
        base_url=config.base_url,
        timeout_s=settings.llm_timeout_s,
    )

