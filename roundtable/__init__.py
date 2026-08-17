"""llm-roundtable: ask a council of LLMs instead of one.

This package has four moving parts. `providers/` wraps each LLM backend
(Anthropic, OpenAI, OpenRouter, Ollama, and a deterministic fake used by
tests) behind one shared `complete()` call. `council.py` runs the four
stages of a roundtable: first opinions, anonymised peer review, chair
synthesis, and a dissent ledger. `transcript.py` writes each run to a
markdown file plus a JSON sidecar and updates a running leaderboard.
`cli.py` is the `roundtable` command you actually type.

See README.md for the idea and `uv run roundtable ask --help` to run it.
"""

__version__ = "0.1.0"
