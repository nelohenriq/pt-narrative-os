"""
pt-media-os — Application Settings

Centralized configuration loaded from environment variables via pydantic-settings.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from .env / environment."""

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}

    # Database
    DATABASE_URL: str = "postgresql://ptmedia:ptmedia@localhost:5432/pt_media_os"

    # AI Providers
    OLLAMA_HOST: str = "http://localhost:11434"
    NVIDIA_NIM_API_KEY: str = ""
    GROQ_API_KEY: str = ""
    OPENROUTER_API_KEY: str = ""

    # Review UI Auth
    REVIEW_USERNAME: str = "admin"
    REVIEW_PASSWORD_HASH: str = ""

    # Scheduling
    INGESTION_CRON: str = "*/30 * * * *"
    INSTITUTIONAL_CRON: str = "0 */4 * * *"
    DIGEST_CRON: str = "0 7 * * *"

    # Embedding / Clustering
    EMBEDDING_DIM: int = 768
    CLUSTERING_SIMILARITY_THRESHOLD: float = 0.85
    CLUSTERING_TIME_WINDOW_HOURS: int = 72
    CLUSTERING_MIN_ARTICLES: int = 2
    CLUSTERING_MIN_OUTLETS: int = 2
    LUSA_SIMILARITY_THRESHOLD: float = 0.88

    # Pipeline tuning
    NORMALIZATION_BATCH_SIZE: int = 50
    EMBEDDING_BATCH_SIZE: int = 20
    ANALYSIS_BATCH_SIZE: int = 10
    MIN_ARTICLE_WORD_COUNT: int = 80

    # App
    APP_ENV: str = "development"
    APP_LOG_LEVEL: str = "INFO"
    APP_PORT: int = 8000
    REVIEW_UI_PORT: int = 8001

    # Redis (optional)
    REDIS_URL: str = ""


@lru_cache
def get_settings() -> Settings:
    """Cached settings singleton."""
    return Settings()


settings = get_settings()
