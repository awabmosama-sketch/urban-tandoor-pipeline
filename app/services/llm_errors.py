"""Exceptions and safe error formatting for LLM providers."""
from __future__ import annotations

import re

_TOKEN_RE = re.compile(
    r"\b(?:sk-[A-Za-z0-9_-]{8,}|AIza[0-9A-Za-z_-]{10,}|AQ\.[0-9A-Za-z_-]{10,})\b"
)


class LLMTimeoutError(Exception):
    """An LLM provider did not respond before the configured timeout."""


class LLMProviderError(Exception):
    """An LLM provider returned an error or unexpected response."""


class LLMConfigurationError(Exception):
    """The selected LLM provider is missing required configuration."""


def redact_secrets(text: str, *secrets: str) -> str:
    """Remove known keys and common token shapes before logging upstream text."""
    result = str(text)
    for secret in secrets:
        if secret:
            result = result.replace(secret, "[redacted]")
    return _TOKEN_RE.sub("[redacted]", result)


__all__ = [
    "LLMConfigurationError",
    "LLMProviderError",
    "LLMTimeoutError",
    "redact_secrets",
]
