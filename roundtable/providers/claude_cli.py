"""claude_cli provider: run council members through the Claude Code CLI itself.

This is the zero-key path. Every other provider needs a vendor API key; this one
shells out to `claude -p`, which is billed to whatever you are logged into (a Claude
subscription), not a metered API key. If you have Claude Code installed and are
logged in, a whole council can run with nothing at all in .env. Model ids are the
CLI's own aliases (`haiku`, `sonnet`, `opus`) or a full model id.

Three real limitations, all because this wraps a CLI built for interactive coding
sessions rather than a raw completion endpoint:

1. No sampling temperature. `claude -p` does not expose one, so `temperature` is
   accepted (to satisfy the shared Provider interface) and silently ignored.
2. No output length cap. There is no `--max-tokens` flag, so `max_tokens` from
   council.yaml is also a no-op here. A wall-clock subprocess timeout is the only
   length control available, and it is a blunt one.
3. Real, and non-trivial, fixed cost per call. Every invocation carries the harness's
   own context (tool definitions, the default system prompt) on top of whatever you
   actually ask, and that shows up as genuine dollar cost even though nothing is
   billed against ANTHROPIC_API_KEY. `--allowedTools ""` and `--strict-mcp-config`
   strip the tool set a normal coding session would carry (a roundtable member
   answering a question has no business holding Bash or Edit access anyway, so this
   is a correctness fix as much as a cost one).

A fourth issue was found and fixed during testing, not just documented: the operator's
personal settings (global CLAUDE.md, memory, project context) can bleed into a council
answer even with a neutral cwd and a fully custom --system-prompt, since neither of
those stops the harness from loading account-level settings. `--setting-sources ""`
tells the CLI to load no settings at all (no user, project, or local scope), which is
what actually stops the leak; a bare custom --system-prompt does not. See the README
design notes for what the leak looked like before this flag was added, and confirm it
for yourself with `claude -p "Where do I live?" --setting-sources ""` versus without.
"""

from __future__ import annotations

import asyncio
import json
import tempfile

from .base import Completion, Provider, ProviderError, Usage

_TIMEOUT_S = 240


class ClaudeCLIProvider(Provider):
    """Claude models via the `claude` CLI, subscription-billed, no API key required."""

    async def complete(
        self,
        *,
        system: str,
        user: str,
        model: str,
        max_tokens: int = 1024,
        temperature: float = 0.7,
    ) -> Completion:
        args = [
            "claude",
            "-p",
            user,
            "--model",
            model,
            "--output-format",
            "json",
            "--allowedTools",
            "",
            "--strict-mcp-config",
            "--setting-sources",
            "",
        ]
        if system:
            args += ["--system-prompt", system]

        try:
            proc = await asyncio.create_subprocess_exec(
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=tempfile.gettempdir(),
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=_TIMEOUT_S)
        except FileNotFoundError as exc:
            raise ProviderError(
                "The `claude` CLI was not found on PATH. Install Claude Code, or configure "
                "a different provider in council.yaml."
            ) from exc
        except asyncio.TimeoutError as exc:
            proc.kill()
            raise ProviderError(f"claude CLI call for model {model!r} timed out after {_TIMEOUT_S}s") from exc

        if proc.returncode != 0:
            raise ProviderError(
                f"claude CLI call for model {model!r} failed (exit {proc.returncode}): "
                f"{stderr.decode(errors='replace')[:500]}"
            )

        try:
            data = json.loads(stdout.decode())
        except json.JSONDecodeError as exc:
            raise ProviderError(
                f"claude CLI returned non-JSON output for model {model!r}: {stdout[:200]!r}"
            ) from exc

        if data.get("is_error"):
            raise ProviderError(f"claude CLI reported an error for model {model!r}: {data.get('result', data)}")

        text = data.get("result", "")
        usage_data = data.get("usage", {}) or {}
        input_tokens = (
            usage_data.get("input_tokens", 0)
            + usage_data.get("cache_creation_input_tokens", 0)
            + usage_data.get("cache_read_input_tokens", 0)
        )
        usage = Usage(
            input_tokens=input_tokens,
            output_tokens=usage_data.get("output_tokens", 0),
            cost_usd=data.get("total_cost_usd", 0.0) or 0.0,
        )
        return Completion(text=text, usage=usage)
