"""OpenRouter provider: one key, many upstream models, OpenAI-compatible.

OpenRouter mirrors the OpenAI chat completions shape, so this is the
shortest provider to read if you want to see the whole pattern in one
place: read OPENROUTER_API_KEY, POST to /chat/completions, pull text and
usage back out. Copy this file (not anthropic.py or openai.py, which carry
SDK-specific handling) as the starting point for a new OpenAI-compatible
backend.
"""

from __future__ import annotations

import os

import httpx

from .base import Completion, Provider, ProviderError, Usage

_BASE_URL = "https://openrouter.ai/api/v1"


class OpenRouterProvider(Provider):
    """Any OpenRouter-hosted model, via plain HTTP (no SDK dependency)."""

    async def complete(
        self,
        *,
        system: str,
        user: str,
        model: str,
        max_tokens: int = 1024,
        temperature: float = 0.7,
    ) -> Completion:
        api_key = os.environ.get("OPENROUTER_API_KEY")
        if not api_key:
            raise ProviderError("OPENROUTER_API_KEY is not set")

        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        headers = {"Authorization": f"Bearer {api_key}"}

        async with httpx.AsyncClient(timeout=120) as client:
            try:
                response = await client.post(f"{_BASE_URL}/chat/completions", json=payload, headers=headers)
                response.raise_for_status()
            except httpx.HTTPError as exc:
                raise ProviderError(f"OpenRouter call failed for model {model!r}: {exc}") from exc

        data = response.json()
        text = data["choices"][0]["message"]["content"] or ""
        usage_data = data.get("usage", {}) or {}
        usage = Usage(
            input_tokens=usage_data.get("prompt_tokens", 0) or 0,
            output_tokens=usage_data.get("completion_tokens", 0) or 0,
        )
        return Completion(text=text, usage=usage)
