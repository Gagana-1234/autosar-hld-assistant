"""
app/rag/llm_provider.py
LLM provider abstraction (Ollama local backend, stub for tests).

Supports:
  - OllamaProvider  — calls local Ollama HTTP API (llama3, mistral, qwen2…)
  - StubProvider    — returns deterministic canned responses (tests / offline)

Factory: get_llm() returns a cached provider based on settings.llm_provider.
"""
from __future__ import annotations

import json
from abc import ABC, abstractmethod
from functools import lru_cache

import requests
from loguru import logger

from app.core.config import get_settings


# ── Abstract base ─────────────────────────────────────────────────────────────

class BaseLLMProvider(ABC):

    @abstractmethod
    def generate(
        self,
        prompt: str,
        system: str = "",
        temperature: float = 0.1,
        max_tokens: int = 1024,
    ) -> str:
        """Generate a response to the given prompt."""


# ── Ollama provider ───────────────────────────────────────────────────────────

class OllamaProvider(BaseLLMProvider):
    """
    Calls the local Ollama REST API.
    Endpoint: POST /api/generate
    Docs: https://github.com/ollama/ollama/blob/main/docs/api.md
    """

    def __init__(self, model: str, base_url: str = "http://localhost:11434"):
        self._model = model
        self._base_url = base_url.rstrip("/")
        logger.info("OllamaProvider initialised: model={} url={}", model, base_url)

    def generate(
        self,
        prompt: str,
        system: str = "",
        temperature: float = 0.1,
        max_tokens: int = 1024,
    ) -> str:
        payload: dict = {
            "model": self._model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            },
        }
        if system:
            payload["system"] = system

        try:
            resp = requests.post(
                f"{self._base_url}/api/generate",
                json=payload,
                timeout=120,
            )
            resp.raise_for_status()
            return resp.json().get("response", "").strip()
        except requests.exceptions.ConnectionError:
            logger.error(
                "Cannot reach Ollama at {}. Is Ollama running?", self._base_url
            )
            raise RuntimeError(
                f"Ollama is not reachable at {self._base_url}. "
                "Please start Ollama with `ollama serve`."
            )
        except requests.exceptions.Timeout:
            logger.error("Ollama request timed out for model {}", self._model)
            raise RuntimeError("Ollama request timed out")
        except Exception as exc:
            logger.error("Ollama error: {}", exc)
            raise


# ── Stub provider ─────────────────────────────────────────────────────────────

class StubLLMProvider(BaseLLMProvider):
    """Returns a fixed canned response — used in unit tests and offline mode."""

    def generate(
        self,
        prompt: str,
        system: str = "",
        temperature: float = 0.1,
        max_tokens: int = 1024,
    ) -> str:
        return (
            "**Stub LLM response** — Ollama is not configured in this environment. "
            "Please set LLM_PROVIDER=ollama and ensure Ollama is running locally."
        )


# ── Factory ───────────────────────────────────────────────────────────────────

@lru_cache(maxsize=1)
def get_llm() -> BaseLLMProvider:
    """Return a cached LLM provider instance."""
    settings = get_settings()
    provider = settings.llm_provider.lower()

    if provider == "stub":
        return StubLLMProvider()

    if provider == "ollama":
        return OllamaProvider(
            model=settings.ollama_model,
            base_url=settings.ollama_base_url,
        )

    logger.warning("Unknown LLM provider '{}', falling back to stub", provider)
    return StubLLMProvider()
