"""Provider registry: maps the `provider:` string in council.yaml to a class.

Instances are created lazily and cached per provider name for the life of a
run, since each one may hold an SDK client or connection pool worth reusing
across the several calls a roundtable makes.
"""

from __future__ import annotations

from .anthropic import AnthropicProvider
from .base import Completion, Provider, ProviderError, Usage
from .claude_cli import ClaudeCLIProvider
from .fake import FakeProvider
from .ollama import OllamaProvider
from .openai import OpenAIProvider
from .openrouter import OpenRouterProvider

_REGISTRY: dict[str, type[Provider]] = {
    "anthropic": AnthropicProvider,
    "openai": OpenAIProvider,
    "openrouter": OpenRouterProvider,
    "ollama": OllamaProvider,
    "claude_cli": ClaudeCLIProvider,
    "fake": FakeProvider,
}

_instances: dict[str, Provider] = {}


def get_provider(name: str) -> Provider:
    """Return a cached provider instance for `name`, creating it on first use."""
    if name not in _REGISTRY:
        known = ", ".join(sorted(_REGISTRY))
        raise ValueError(f"Unknown provider {name!r}. Known providers: {known}")
    if name not in _instances:
        _instances[name] = _REGISTRY[name]()
    return _instances[name]


def reset_providers() -> None:
    """Drop cached provider instances. Mainly useful for tests."""
    _instances.clear()


__all__ = ["Completion", "Provider", "ProviderError", "Usage", "get_provider", "reset_providers"]
