# Makefile: convenience wrappers around `uv run`. See README.md for the full quick start.

.PHONY: test dry-run ask leaderboard

test:
	uv run pytest -q

dry-run:
	uv run roundtable ask "Should a small team adopt a monorepo?" --dry-run

# Usage: make ask Q="your question here"
ask:
	uv run roundtable ask "$(Q)"

leaderboard:
	uv run roundtable leaderboard
