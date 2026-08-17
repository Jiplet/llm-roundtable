"""Anthropic provider: wraps the Claude Messages API behind the shared Provider interface.

Reads ANTHROPIC_API_KEY from the environment (via the SDK's own lookup).
One AsyncAnthropic client is created lazily and reused for every call a
member makes, rather than one per call, since the client holds a connection
pool worth keeping warm across a run.
"""

from __future__ import annotations

from .base import Completion, Provider, ProviderError, Usage


class AnthropicProvider(Provider):
    """Claude models via the official `anthropic` SDK."""

    def __init__(self) -> None:
        self._client = None

    def _client_or_create(self):
        if self._client is None:
            import anthropic

            self._client = anthropic.AsyncAnthropic()
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
        try:
            response = await client.messages.create(
                model=model,
                max_tokens=max_tokens,
                temperature=temperature,
                system=system,
                messages=[{"role": "user", "content": user}],
            )
        except Exception as exc:  # noqa: BLE001 - surfaced as one provider-level error
            raise ProviderError(f"Anthropic call failed for model {model!r}: {exc}") from exc

        text = "".join(block.text for block in response.content if getattr(block, "type", "") == "text")
        usage = Usage(
            input_tokens=getattr(response.usage, "input_tokens", 0) or 0,
            output_tokens=getattr(response.usage, "output_tokens", 0) or 0,
        )
        return Completion(text=text, usage=usage)
