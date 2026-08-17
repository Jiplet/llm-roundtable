"""claude_cli provider: verifies the subprocess argv carries the flags this provider
depends on for a safe, unbiased council answer (no tool access, no account settings
bleeding into what is meant to be an independent opinion). No real subprocess runs
here: asyncio.create_subprocess_exec is monkeypatched to capture the argv and return
a canned JSON payload, so this test needs no `claude` CLI on PATH and no network.
"""

import json

import pytest

from roundtable.providers.claude_cli import ClaudeCLIProvider


class _FakeProcess:
    def __init__(self, stdout: bytes, returncode: int = 0):
        self._stdout = stdout
        self.returncode = returncode

    async def communicate(self):
        return self._stdout, b""


@pytest.mark.asyncio
async def test_argv_isolates_settings_and_strips_tools(monkeypatch):
    captured = {}

    async def fake_create_subprocess_exec(*args, **kwargs):
        captured["args"] = args
        payload = json.dumps({"result": "ok", "usage": {}, "is_error": False}).encode()
        return _FakeProcess(payload)

    monkeypatch.setattr("asyncio.create_subprocess_exec", fake_create_subprocess_exec)

    provider = ClaudeCLIProvider()
    await provider.complete(system="be helpful", user="hi", model="haiku")

    argv = list(captured["args"])

    # --setting-sources "" is the fix for the context-leak bug: without it, the
    # operator's personal CLAUDE.md/memory can bleed into a council answer.
    assert "--setting-sources" in argv
    assert argv[argv.index("--setting-sources") + 1] == ""

    # A council member answering a question has no business holding tool access.
    assert "--allowedTools" in argv
    assert argv[argv.index("--allowedTools") + 1] == ""
    assert "--strict-mcp-config" in argv


@pytest.mark.asyncio
async def test_complete_returns_result_text_and_usage(monkeypatch):
    async def fake_create_subprocess_exec(*args, **kwargs):
        payload = json.dumps({
            "result": "hello",
            "is_error": False,
            "total_cost_usd": 0.01,
            "usage": {"input_tokens": 5, "cache_creation_input_tokens": 10,
                      "cache_read_input_tokens": 0, "output_tokens": 3},
        }).encode()
        return _FakeProcess(payload)

    monkeypatch.setattr("asyncio.create_subprocess_exec", fake_create_subprocess_exec)

    provider = ClaudeCLIProvider()
    completion = await provider.complete(system="", user="hi", model="haiku")

    assert completion.text == "hello"
    assert completion.usage.input_tokens == 15
    assert completion.usage.output_tokens == 3
    assert completion.usage.cost_usd == 0.01
