"""AsyncOpenAI clients for all AI providers used in pt-narrative-os.

Each provider gets its own factory function returning a pre-configured
AsyncOpenAI client. Provider-specific base URLs and API keys are read from
the environment via pydantic-settings.

Providers:
    - ollama: local embeddings (nomic-embed-text) + fast extraction (mistral)
    - nvidia_nim: cloud — primary for framing/summarization
    - groq: cloud — fallback for framing/summarization
    - openrouter: cloud — last-resort fallback
"""

from __future__ import annotations

import os
from typing import Literal

from openai import AsyncOpenAI

ProviderName = Literal["ollama", "nvidia_nim", "groq", "openrouter"]


# ──────────────────────────────────────────────────────────────────────────────
# Individual client factories
# ──────────────────────────────────────────────────────────────────────────────


def get_ollama_client() -> AsyncOpenAI:
    """Ollama — local inference (embeddings + fast extraction)."""
    return AsyncOpenAI(
        base_url=f"{os.getenv('OLLAMA_HOST', 'http://localhost:11434')}/v1",
        api_key="ollama",  # Ollama doesn't require a real key
    )


def get_nvidia_nim_client() -> AsyncOpenAI:
    """NVIDIA NIM — cloud API for framing analysis and summarization.

    Free tier: 1,000 credits, 40 RPM.
    Always use response_format=json_object with NIM (tool-calling is unreliable).
    """
    return AsyncOpenAI(
        base_url="https://integrate.api.nvidia.com/v1",
        api_key=os.getenv("NVIDIA_NIM_API_KEY", "nvapi-"),
    )


def get_groq_client() -> AsyncOpenAI:
    """Groq — fast cloud inference, fallback for NIM tasks.

    Free tier: 30 RPM, 14,400 tokens/day.
    """
    return AsyncOpenAI(
        base_url="https://api.groq.com/openai/v1",
        api_key=os.getenv("GROQ_API_KEY", ""),
    )


def get_openrouter_client() -> AsyncOpenAI:
    """OpenRouter — last-resort fallback."""
    return AsyncOpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=os.getenv("OPENROUTER_API_KEY", ""),
    )


# ──────────────────────────────────────────────────────────────────────────────
# Unified accessor
# ──────────────────────────────────────────────────────────────────────────────

# Lazy-initialised cache — clients are created once then reused.
_client_cache: dict[str, AsyncOpenAI] = {}

_FACTORIES = {
    "ollama": get_ollama_client,
    "nvidia_nim": get_nvidia_nim_client,
    "groq": get_groq_client,
    "openrouter": get_openrouter_client,
}


def get_client(provider: ProviderName) -> AsyncOpenAI:
    """Return a cached AsyncOpenAI client for the given provider."""
    if provider not in _client_cache:
        if provider not in _FACTORIES:
            raise ValueError(
                f"Unknown provider: {provider!r}. Expected one of: "
                f"{', '.join(sorted(_FACTORIES))}"
            )
        _client_cache[provider] = _FACTORIES[provider]()
    return _client_cache[provider]