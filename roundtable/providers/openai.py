"""OpenAI provider: wraps Chat Completions behind the shared Provider interface.

Reads OPENAI_API_KEY from the environment (via the SDK's own lookup).

Two real gotchas found while building this, both handled with a one-shot
retry rather than a hard failure:

1. Newer "reasoning" model families (the o1/o3/gpt-5 lines at time of
   writing) reject the `max_tokens` parameter and want `max_completion_tokens`
   instead. We try `max_tokens` first (it works for everything else) and
   retry once with `max_completion_tokens` if the API complains about it.
2. The same families sometimes reject a non-default `temperature` (they only
   accept the default, 1). We retry once with `temperature` dropped if the
   API complains about that specifically. This is a silent quality trade-off
   worth knowing about: you lose control of sampling temperature for those
   models. See README design notes for what this looked like in practice.
"""

from __future__ import annotations

from .base import Completion, Provider, ProviderError, Usage


class OpenAIProvider(Provider):
    """OpenAI models via the official `openai` SDK."""

    def __init__(self) -> None:
        self._client = None

    def _client_or_create(self):
        if self._client is None:
            import openai

            self._client = openai.AsyncOpenAI()
        return self._client

    async def complete(
        self,
        *,
        system: str,
        user: str,
        model: str,
        max_tokens: int = 1024,
        temperature: float = 0.7,
    ) -> Completion:
        client = self._client_or_create()
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]

        kwargs: dict = {"model": model, "messages": messages, "max_tokens": max_tokens, "temperature": temperature}
        try:
            response = await client.chat.completions.create(**kwargs)
        except Exception as exc:  # noqa: BLE001
            message = str(exc)
            if "max_tokens" in message and "max_completion_tokens" in message:
                kwargs.pop("max_tokens")
                kwargs["max_completion_tokens"] = max_tokens
                try:
                    response = await client.chat.completions.create(**kwargs)
                except Exception as exc2:  # noqa: BLE001
                    raise ProviderError(f"OpenAI call failed for model {model!r}: {exc2}") from exc2
            elif "temperature" in message.lower():
                kwargs.pop("temperature", None)
                try:
                    response = await client.chat.completions.create(**kwargs)
                except Exception as exc2:  # noqa: BLE001
                    raise ProviderError(f"OpenAI call failed for model {model!r}: {exc2}") from exc2
            else:
                raise ProviderError(f"OpenAI call failed for model {model!r}: {exc}") from exc

        choice = response.choices[0]
        text = choice.message.content or ""
        usage = Usage(
            input_tokens=getattr(response.usage, "prompt_tokens", 0) or 0,
            output_tokens=getattr(response.usage, "completion_tokens", 0) or 0,
        )
        return Completion(text=text, usage=usage)
