"""Provider interface: every LLM backend implements one async call.

A provider takes a system prompt, a user prompt, a model id, and generation
settings, and returns the reply text plus a token usage count. The council
code (see ../council.py) never talks to a vendor SDK directly. It calls
whichever provider a member is configured with, through this same shape, so
adding a new backend means writing one small file, not touching the council
logic. See openrouter.py for the shortest example to copy from.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass


@dataclass
class Usage:
    """Token counts for one completion call. Zero when a backend does not report them.

    `cost_usd` is populated only by backends that report real dollar cost themselves
    (currently claude_cli, which gets it for free from the CLI's own JSON output).
    Left at 0.0 elsewhere: this repo does not maintain its own per-model price table,
    since those go stale the moment a provider changes pricing.
    """

    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0


@dataclass
class Completion:
    """The result of one provider call: the reply text and its token usage."""

    text: str
    usage: Usage


class ProviderError(RuntimeError):
    """Raised when a provider call fails after any built-in retries are exhausted."""


class Provider(abc.ABC):
    """Base class every provider backend implements."""

    @abc.abstractmethod
    async def complete(
        self,
        *,
        system: str,
        user: str,
        model: str,
        max_tokens: int = 1024,
        temperature: float = 0.7,
    ) -> Completion:
        """Send one prompt, return one completion.

        Raises ProviderError (or lets the underlying SDK's exception through)
        on transport or API failures. Callers do not need to catch anything
        provider-specific: ProviderError is the one type worth handling.
        """
        raise NotImplementedError
