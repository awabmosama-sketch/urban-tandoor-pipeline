"""Application settings loaded from the environment / `.env`."""

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Typed view over the environment used by the pipeline."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Application
    app_env: str = "dev"

    # Database (engine wiring comes later)
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/urban_tandoor"

    # Embeddings
    embedding_provider: Literal["openai", "gemini", "fake"] = "openai"
    embedding_model: str = "text-embedding-3-small"
    embedding_dim: int = 1536
    openai_api_key: str = ""
    gemini_api_key: str = ""

    # Ingestion
    data_dir: str = "./data"
    chunk_size: int = Field(default=800, gt=0)
    chunk_overlap: int = Field(default=120, ge=0)

    # Admin
    admin_token: str = "change-me"
    admin_job_max_history: int = 100

    # Groq (AI concierge — key stays server-side)
    groq_api_key: str = ""
    groq_model: str = "openai/gpt-oss-120b"
    groq_base_url: str = "https://api.groq.com/openai/v1"
    groq_timeout_s: float = 30.0


@lru_cache
def get_settings() -> Settings:
    """Return a process-wide cached `Settings` instance."""
    return Settings()
