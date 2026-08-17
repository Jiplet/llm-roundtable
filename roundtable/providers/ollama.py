"""Ollama provider: local models, no API key, no network call leaves the machine.

Talks to Ollama's native /api/chat endpoint. Base URL comes from the
OLLAMA_HOST environment variable, defaulting to the standard local address.
Useful for running the whole council on-box: see the README's "use only
local Ollama models" adapting note.
"""

from __future__ import annotations

import os

import httpx

from .base import Completion, Provider, ProviderError, Usage

_DEFAULT_HOST = "http://localhost:11434"


class OllamaProvider(Provider):
    """Any locally pulled Ollama model, via plain HTTP."""

    async def complete(
        self,
        *,
        system: str,
        user: str,
        model: str,
        max_tokens: int = 1024,
        temperature: float = 0.7,
    ) -> Completion:
        host = os.environ.get("OLLAMA_HOST", _DEFAULT_HOST).rstrip("/")
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "stream": False,
            "options": {"temperature": temperature, "num_predict": max_tokens},
        }

        async with httpx.AsyncClient(timeout=300) as client:
            try:
                response = await client.post(f"{host}/api/chat", json=payload)
                response.raise_for_status()
            except httpx.HTTPError as exc:
                raise ProviderError(
                    f"Ollama call failed for model {model!r} at {host}: {exc}. "
                    "Is `ollama serve` running and has the model been pulled?"
                ) from exc

        data = response.json()
        text = data.get("message", {}).get("content", "") or ""
        usage = Usage(
            input_tokens=data.get("prompt_eval_count", 0) or 0,
            output_tokens=data.get("eval_count", 0) or 0,
        )
        return Completion(text=text, usage=usage)
