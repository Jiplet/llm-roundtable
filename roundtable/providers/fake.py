"""Deterministic fake provider: no network calls, used by tests and --dry-run.

Real providers depend on network access and API keys, which makes them
unsuitable for a test suite that has to run offline and for a `--dry-run`
flag that lets a stranger try the CLI before they own any keys. FakeProvider
returns canned, deterministic text keyed off the member's name and whatever
role the prompt asks it to play (first opinion, peer review, chair synthesis,
dissent ledger), so the rest of the pipeline (parsing, transcript writing,
leaderboard maths) gets exercised end to end without ever leaving the
laptop. The canned review text is deliberately well-formed against the
format `council.py` asks reviewers to use, so a dry run produces a complete,
readable transcript rather than an empty one.
"""

from __future__ import annotations

from .base import Completion, Provider, Usage


# Short, varied canned opinions so a dry-run transcript reads like an actual
# (if generic) roundtable rather than four copies of the same paragraph.
_OPINIONS = [
    "On balance, yes, but only once the team has felt the pain the change is meant to "
    "fix. Adopt it for a concrete reason (shared release cadence, duplicated tooling, a "
    "cross-cutting refactor that keeps stalling at the repo boundary), not as a default.",
    "The deciding factor is release coupling, not repo count. If the pieces ship together "
    "and break together, a single repo removes a coordination tax. If they do not, a "
    "monorepo mostly adds build-graph complexity without buying anything back.",
    "Start from the failure mode you are trying to avoid. Version-skew bugs across "
    "services point toward one repo; one team blocking another's CI point away from it. "
    "Pick the structure that matches the actual failure you have seen, not the one you fear.",
]

_REVIEW_NOTES = [
    "Concrete and testable: gives a condition to check rather than a rule of thumb.",
    "Reasonable but generic: the claim is true of most tooling decisions, not specific to this one.",
    "Grounded in a failure mode, which is the right lens, but light on how to weigh conflicting signals.",
]


def _hash_index(key: str, modulo: int) -> int:
    """Stable, deterministic index derived from a string. Not cryptographic, just repeatable."""
    return sum(ord(c) for c in key) % modulo


class FakeProvider(Provider):
    """Canned responses, indexed by member name and prompt shape. No I/O."""

    async def complete(
        self,
        *,
        system: str,
        user: str,
        model: str,
        max_tokens: int = 1024,
        temperature: float = 0.7,
    ) -> Completion:
        text = self._render(system=system, user=user, model=model)
        # Fake token counts so transcripts and leaderboard maths have something
        # to display; roughly 4 characters per token, the usual rough estimate.
        usage = Usage(
            input_tokens=max(1, len(system + user) // 4),
            output_tokens=max(1, len(text) // 4),
        )
        return Completion(text=text, usage=usage)

    def _render(self, *, system: str, user: str, model: str) -> str:
        # Dispatch on the SYSTEM prompt, not the user prompt: council.py's four stage
        # instructions (_OPINION_INSTRUCTION, _REVIEW_INSTRUCTION, _SYNTHESIS_INSTRUCTION,
        # _DISSENT_INSTRUCTION) are stable, distinct strings. The user prompt is not a safe
        # signal, since by stage 3 it quotes earlier stages' output verbatim (a reviewer's
        # "the response was..." reasoning, for instance), which can accidentally match
        # keywords meant to identify a different stage.
        sys_lower = system.lower()
        if "dissent ledger" in sys_lower:
            return self._render_dissent(user)
        if "peer-reviewing" in sys_lower:
            return self._render_review(user)
        if "chair of a roundtable" in sys_lower:
            return self._render_synthesis(user)
        return self._render_opinion(model, user)

    def _render_opinion(self, model: str, user: str) -> str:
        idx = _hash_index(model, len(_OPINIONS))
        return f"[{model}'s view]\n\n{_OPINIONS[idx]}"

    def _render_review(self, user: str) -> str:
        # Pull out the response labels the reviewer prompt actually presented,
        # so the canned review always matches what it was asked to score.
        labels = []
        for line in user.splitlines():
            line = line.strip()
            if line.startswith("Response ") and line.endswith(":"):
                label = line[len("Response ") : -1].strip()
                if label and label not in labels:
                    labels.append(label)
        if not labels:
            labels = ["A", "B"]

        blocks = []
        for i, label in enumerate(labels):
            note = _REVIEW_NOTES[i % len(_REVIEW_NOTES)]
            accuracy = 8 - (i % 3)
            insight = 6 + (i % 4)
            completeness = 7 - (i % 2)
            blocks.append(
                f"## Response {label}\n"
                f"Accuracy: {accuracy}/10\n"
                f"Insight: {insight}/10\n"
                f"Completeness: {completeness}/10\n"
                f"Notes: {note}"
            )
        ranking = " > ".join(labels)
        return (
            "\n\n".join(blocks)
            + f"\n\nRANKING: {ranking}\n"
            + "REASONING: Favoured the response with the most testable, decision-shaped claim."
        )

    def _render_synthesis(self, user: str) -> str:
        return (
            "Chair synthesis (fake provider): the council converges on a conditional "
            "answer rather than a flat yes or no. Adopt the change when the failure mode "
            "it fixes has actually been observed; treat it as a default otherwise, and "
            "revisit once a specific, named pain point shows up."
        )

    def _render_dissent(self, user: str) -> str:
        return (
            "### Dissent ledger (fake provider)\n\n"
            "1. **Claim in dispute:** whether the decision should default to yes or default to no.\n"
            "   - Member 1: default to no until a concrete failure mode is observed.\n"
            "   - Member 2: default to yes once release coupling is confirmed, without "
            "waiting for a failure.\n"
            "   - Minority view: Member 2's earlier trigger point.\n"
            "   - What would settle it: a small pilot measuring coordination overhead "
            "before and after, over one release cycle.\n"
            "   - Chair's decision: kept the conditional framing and named the pilot as "
            "the next step rather than picking a side outright."
        )
