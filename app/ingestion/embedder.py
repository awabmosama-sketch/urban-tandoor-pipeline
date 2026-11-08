"""
Embedding provider abstraction. Deterministic FakeEmbedder enables
offline development and idempotent re-runs. Switch to real providers
by setting EMBEDDING_PROVIDER=openai or gemini in .env.
"""
from __future__ import annotations

import hashlib
from abc import ABC, abstractmethod

import numpy as np

from app.config import get_settings


class Embedder(ABC):
    dim: int
    @abstractmethod
    async def embed_batch(self, texts: list[str]) -> list[list[float]]: ...


class FakeEmbedder(Embedder):
    """Deterministic unit-normalized vectors. Same text -> same vector.
    Enables idempotency tests and offline development. NOT semantically
    meaningful — real semantic search needs a real provider."""
    def __init__(self, dim: int) -> None:
        self.dim = dim

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        out: list[list[float]] = []
        for text in texts:
            h = hashlib.sha256(text.encode("utf-8")).digest()
            seed = int.from_bytes(h[:8], "big") % (2**32)
            rng = np.random.default_rng(seed)
            vec = rng.standard_normal(self.dim).astype(np.float64)
            norm = float(np.linalg.norm(vec))
            if norm > 0:
                vec = vec / norm
            out.append(vec.tolist())
        return out


class OpenAIEmbedder(Embedder):
    def __init__(self, model: str, dim: int) -> None:
        self.model = model
        self.dim = dim
        self._client = None

    def _client_lazy(self):
        if self._client is None:
            from openai import AsyncOpenAI
            self._client = AsyncOpenAI(api_key=get_settings().openai_api_key)
        return self._client

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        client = self._client_lazy()
        resp = await client.embeddings.create(model=self.model, input=texts)
        return [d.embedding for d in resp.data]


class GeminiEmbedder(Embedder):
    """Gemini text-embedding-004 produces 768-dim vectors by default.
    IMPORTANT: if switching to this, also set EMBEDDING_DIM=768 and re-ingest
    the docs domain so every chunk is re-embedded at the new dimension."""
    def __init__(self, model: str, dim: int) -> None:
        self.model = model
        self.dim = dim

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        raise NotImplementedError(
            "Gemini embedder not wired. To use it: set EMBEDDING_PROVIDER=gemini, "
            "EMBEDDING_MODEL=text-embedding-004, EMBEDDING_DIM=768 in .env, then "
            "run `utg-ingest --only docs --wipe --yes` to re-embed all chunks."
        )


_cached: Embedder | None = None


def get_embedder() -> Embedder:
    global _cached
    if _cached is None:
        s = get_settings()
        if s.embedding_provider == "fake":
            _cached = FakeEmbedder(dim=s.embedding_dim)
        elif s.embedding_provider == "openai":
            _cached = OpenAIEmbedder(model=s.embedding_model, dim=s.embedding_dim)
        elif s.embedding_provider == "gemini":
            _cached = GeminiEmbedder(model=s.embedding_model, dim=s.embedding_dim)
        else:
            raise ValueError(f"Unknown EMBEDDING_PROVIDER: {s.embedding_provider}")
    return _cached


def reset_embedder() -> None:
    """For tests that need a fresh embedder."""
    global _cached
    _cached = None
