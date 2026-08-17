"""The four stages of a roundtable: opinions, review, synthesis, dissent.

Stage 1 (first opinions) asks every member the question independently and in
parallel. No member sees another's answer at this point: that is the whole
point of asking more than one model.

Stage 2 (anonymised peer review) has every member score and rank the other
members' answers, with identities hidden. Each reviewer gets its own shuffle
of Response A / B / C labels (see build_shuffle_map): a reviewer's own
answer is excluded, and no two reviewers see the same label assigned to the
same author, so a model cannot learn "I am always B" and game its scoring.

Stage 3 (chair synthesis) hands one designated member (the chair) the
question, every first opinion, and the peer review results, and asks it to
write the final answer.

Stage 4 (the dissent ledger) is the part a single-model answer cannot give
you: where the council actually disagreed, what the minority view was, what
would settle the disagreement, and what the chair did about it. It reuses a
second, separate anonymisation scheme from stage 2's (see build_global_label_map)
so the written record stays neutral even though, by this point, a reader who
wants to could match content back to the stage 1 attributions. See the
README's design notes for why that is a deliberate, not an accidental,
choice.
"""

from __future__ import annotations

import asyncio
import re
import time
from dataclasses import dataclass, field

from .providers.base import Provider, ProviderError, Usage

DEFAULT_RUBRIC = ["accuracy", "insight", "completeness"]


# --------------------------------------------------------------------------
# Data shapes
# --------------------------------------------------------------------------


@dataclass
class Member:
    """One council member: a name, a provider/model pair, and its lens (if any)."""

    name: str
    provider: str
    model: str
    temperature: float = 0.7
    lens: str = ""


@dataclass
class CallRecord:
    """Timing and token usage for one provider call, kept for the transcript."""

    stage: str
    member: str
    elapsed_s: float
    usage: Usage


@dataclass
class ResponseScore:
    """One reviewer's scores for one anonymised response."""

    label: str
    scores: dict[str, int]
    notes: str


@dataclass
class ReviewResult:
    """One reviewer's full output: per-response scores plus an overall ranking."""

    reviewer: str
    scores: list[ResponseScore]
    ranking: list[str]  # labels, best to worst, as given to this reviewer
    reasoning: str
    fallback_used: bool
    raw: str
    label_map: dict[str, str] = field(default_factory=dict)  # label -> real member name

    @property
    def resolved_ranking(self) -> list[str]:
        """Ranking with labels resolved back to real member names."""
        return [self.label_map[label] for label in self.ranking if label in self.label_map]


@dataclass
class RunResult:
    """Everything produced by one roundtable run, ready for transcript.py to write out."""

    question: str
    members: list[Member]
    chair: str
    opinions: dict[str, str]
    reviews: list[ReviewResult]
    synthesis: str
    dissent: str
    calls: list[CallRecord]


# --------------------------------------------------------------------------
# Stage 1: first opinions
# --------------------------------------------------------------------------

_STYLE_NOTE = "Never use an em dash: use a colon, a comma, or a rewrite instead."

_OPINION_INSTRUCTION = (
    "You are one independent member of a roundtable of advisors answering the same "
    "question. Give your own direct, complete answer. You cannot see what the other "
    f"members will say, and should not pretend otherwise. {_STYLE_NOTE}"
)


async def run_opinion_stage(
    members: list[Member],
    question: str,
    *,
    provider_for,
    max_tokens: int,
    calls: list[CallRecord],
) -> dict[str, str]:
    """Run stage 1: every member answers the question independently, in parallel."""

    async def ask_one(member: Member) -> tuple[str, str]:
        system = f"{member.lens}\n\n{_OPINION_INSTRUCTION}".strip() if member.lens else _OPINION_INSTRUCTION
        provider: Provider = provider_for(member.provider)
        start = time.monotonic()
        completion = await provider.complete(
            system=system, user=question, model=member.model, max_tokens=max_tokens, temperature=member.temperature
        )
        calls.append(CallRecord("opinion", member.name, time.monotonic() - start, completion.usage))
        return member.name, completion.text

    results = await asyncio.gather(*(ask_one(m) for m in members))
    return dict(results)


# --------------------------------------------------------------------------
# Stage 2: anonymised peer review
# --------------------------------------------------------------------------


def build_shuffle_map(reviewer: str, member_names: list[str], seed: int) -> dict[str, str]:
    """Build one reviewer's label -> real-name map: self excluded, shuffled by `seed`.

    Each reviewer gets an independent shuffle (different reviewers, same run,
    get different label assignments for the same author) but is stable for a
    given (reviewer, seed) pair, so the same run can be replayed for tests
    or debugging without the labels moving under you.
    """
    import random

    others = [name for name in member_names if name != reviewer]
    rng = random.Random(seed)
    shuffled = others[:]
    rng.shuffle(shuffled)
    labels = [chr(ord("A") + i) for i in range(len(shuffled))]
    return dict(zip(labels, shuffled))


def _review_seed(run_seed: int, reviewer: str) -> int:
    return (run_seed * 1_000_003 + hash(reviewer)) & 0xFFFFFFFF


def _rubric_format_block(rubric: list[str]) -> str:
    lines = [f"{dim.capitalize()}: <score>/10" for dim in rubric]
    return "\n".join(lines)


def build_review_prompt(question: str, label_map: dict[str, str], opinions: dict[str, str], rubric: list[str]) -> str:
    """Build the user prompt a reviewer sees: the question plus anonymised responses."""
    parts = [f"Question:\n{question}\n"]
    for label in sorted(label_map):
        parts.append(f"Response {label}:\n{opinions[label_map[label]]}\n")
    labels_in_order = " > ".join(sorted(label_map))
    parts.append(
        "Score each response on the rubric below, then give an overall ranking from best "
        "to worst. Do not try to guess who wrote which response. Use exactly this format, "
        "repeated once per response:\n\n"
        "## Response <LABEL>\n"
        f"{_rubric_format_block(rubric)}\n"
        "Notes: <one or two sentences>\n\n"
        f"Then finish with:\nRANKING: <LABEL> > <LABEL> (e.g. {labels_in_order})\n"
        "REASONING: <one or two sentences on why this order>"
    )
    return "\n".join(parts)


_REVIEW_INSTRUCTION = (
    "You are peer-reviewing anonymised answers from other advisors in a roundtable. "
    "You do not know which model wrote which response, and should not guess. Be exacting: "
    "reward answers that are specific and checkable over answers that are merely confident. "
    f"{_STYLE_NOTE}"
)

_RESPONSE_BLOCK_RE = re.compile(r"##\s*Response\s+([A-Za-z])\s*\n(.*?)(?=\n##\s*Response|\nRANKING:|\Z)", re.S | re.I)
_RANKING_LINE_RE = re.compile(r"RANKING:\s*(.+)", re.I)
_REASONING_LINE_RE = re.compile(r"REASONING:\s*(.+)", re.I)


def parse_review(text: str, valid_labels: list[str], rubric: list[str] | None = None) -> ReviewResult:
    """Parse a reviewer's free-text response into scores plus a ranking.

    Tries the structured `## Response X` / `RANKING:` format first. Falls
    back, in order, to (a) deriving a ranking from summed rubric scores if
    the RANKING line is missing or incomplete, then (b) hunting for any
    `A > B > C`-shaped fragment naming the valid labels anywhere in the
    text, then (c) the presentation order itself, so a run never crashes on
    a model that ignored the format: it just gets flagged with
    `fallback_used=True` so a caller can decide how much to trust it.
    """
    rubric = rubric or DEFAULT_RUBRIC
    valid = set(valid_labels)

    scores: list[ResponseScore] = []
    for match in _RESPONSE_BLOCK_RE.finditer(text):
        label = match.group(1).upper()
        if label not in valid:
            continue
        block = match.group(2)
        dim_scores: dict[str, int] = {}
        for dim in rubric:
            m = re.search(rf"{re.escape(dim)}\s*:?\s*(\d+)\s*/\s*10", block, re.I)
            if m:
                dim_scores[dim] = int(m.group(1))
        notes_match = re.search(r"Notes:\s*(.+)", block, re.I)
        notes = notes_match.group(1).strip() if notes_match else ""
        scores.append(ResponseScore(label=label, scores=dim_scores, notes=notes))

    fallback_used = False
    ranking: list[str] = []

    ranking_match = _RANKING_LINE_RE.search(text)
    if ranking_match:
        label_pattern = "|".join(re.escape(lbl) for lbl in valid_labels)
        found = re.findall(rf"\b({label_pattern})\b", ranking_match.group(1), re.I)
        ranking = [lbl.upper() for lbl in found]
        # dedupe while preserving order, in case a sloppy line repeats a label
        seen: set[str] = set()
        ranking = [lbl for lbl in ranking if lbl not in seen and not seen.add(lbl)]

    if not ranking or set(ranking) != valid:
        fallback_used = True
        if scores:
            # Rank by summed rubric score, descending; stable on ties (first-seen order).
            totals = {s.label: sum(s.scores.values()) for s in scores}
            for label in valid_labels:
                totals.setdefault(label, -1)
            ranking = sorted(valid_labels, key=lambda lbl: (-totals[lbl], valid_labels.index(lbl)))
        else:
            # Last resort: hunt for any "A > B" fragment anywhere in the raw text.
            label_pattern = "|".join(re.escape(lbl) for lbl in valid_labels)
            found = re.findall(rf"\b({label_pattern})\b", text, re.I)
            found = [lbl.upper() for lbl in found]
            seen = set()
            found = [lbl for lbl in found if lbl not in seen and not seen.add(lbl)]
            remaining = [lbl for lbl in valid_labels if lbl not in found]
            ranking = found + remaining

    reasoning_match = _REASONING_LINE_RE.search(text)
    reasoning = reasoning_match.group(1).strip() if reasoning_match else ""

    return ReviewResult(
        reviewer="",
        scores=scores,
        ranking=ranking,
        reasoning=reasoning,
        fallback_used=fallback_used,
        raw=text,
    )


async def run_review_stage(
    members: list[Member],
    question: str,
    opinions: dict[str, str],
    *,
    provider_for,
    rubric: list[str],
    max_tokens: int,
    run_seed: int,
    calls: list[CallRecord],
) -> list[ReviewResult]:
    """Run stage 2: every member reviews the others, with per-reviewer anonymisation."""
    member_names = [m.name for m in members]
    members_by_name = {m.name: m for m in members}

    async def review_one(reviewer_name: str) -> ReviewResult:
        label_map = build_shuffle_map(reviewer_name, member_names, seed=_review_seed(run_seed, reviewer_name))
        prompt = build_review_prompt(question, label_map, opinions, rubric)
        member = members_by_name[reviewer_name]
        provider: Provider = provider_for(member.provider)
        start = time.monotonic()
        completion = await provider.complete(
            system=_REVIEW_INSTRUCTION, user=prompt, model=member.model, max_tokens=max_tokens, temperature=0.2
        )
        calls.append(CallRecord("review", reviewer_name, time.monotonic() - start, completion.usage))
        result = parse_review(completion.text, valid_labels=list(label_map.keys()), rubric=rubric)
        result.reviewer = reviewer_name
        result.label_map = label_map
        return result

    return list(await asyncio.gather(*(review_one(name) for name in member_names)))


# --------------------------------------------------------------------------
# Stage 3: chair synthesis
# --------------------------------------------------------------------------

_SYNTHESIS_INSTRUCTION = (
    "You are the chair of a roundtable of advisors. You have every member's independent "
    "first answer and the peer review each member gave the others. Write the final answer: "
    "synthesise the strongest points, resolve disagreements where you can, and say plainly "
    f"where you are making a judgement call rather than reporting a consensus. {_STYLE_NOTE}"
)


def build_synthesis_prompt(question: str, opinions: dict[str, str], reviews: list[ReviewResult]) -> str:
    parts = [f"Question:\n{question}\n", "First opinions:\n"]
    for name, text in opinions.items():
        parts.append(f"--- {name} ---\n{text}\n")
    parts.append("\nPeer review summaries (reviewer -> ranking of the others, best to worst):\n")
    for review in reviews:
        ranking = " > ".join(review.resolved_ranking) or "(no ranking parsed)"
        parts.append(f"- {review.reviewer} ranked: {ranking}. Reasoning: {review.reasoning or '(none given)'}")
    parts.append("\nWrite the final synthesised answer now.")
    return "\n".join(parts)


async def run_synthesis_stage(
    chair: Member,
    question: str,
    opinions: dict[str, str],
    reviews: list[ReviewResult],
    *,
    provider_for,
    max_tokens: int,
    calls: list[CallRecord],
) -> str:
    """Run stage 3: the chair reads everything and writes the final answer."""
    prompt = build_synthesis_prompt(question, opinions, reviews)
    provider: Provider = provider_for(chair.provider)
    start = time.monotonic()
    completion = await provider.complete(
        system=_SYNTHESIS_INSTRUCTION, user=prompt, model=chair.model, max_tokens=max_tokens, temperature=chair.temperature
    )
    calls.append(CallRecord("synthesis", chair.name, time.monotonic() - start, completion.usage))
    return completion.text


# --------------------------------------------------------------------------
# Stage 4: dissent ledger
# --------------------------------------------------------------------------


def build_global_label_map(member_names: list[str]) -> dict[str, str]:
    """A single, non-shuffled label map used only for the dissent ledger.

    Deliberately a different scheme from stage 2's per-reviewer shuffle (see
    module docstring and README design notes): "Member 1" / "Member 2"
    rather than "Response A" / "Response B", so the two anonymisation
    schemes are never confused with each other in a prompt or a transcript.
    """
    return {f"Member {i + 1}": name for i, name in enumerate(member_names)}


_DISSENT_INSTRUCTION = (
    "You are writing the dissent ledger for a roundtable: the part of the record that says "
    "where the members actually disagreed, not just what the final answer was. Refer to "
    "members only by the Member N labels given below, not by name or model. For each real "
    "disagreement (skip this entirely if the members substantially agreed): state the claim "
    "in dispute, each side's position by label, which position was the minority, what "
    "evidence or test would settle it, and what you (the chair) decided to do about it in "
    "the final answer. Structure it as a numbered list. If there was no real disagreement, "
    f"say so in one line instead of inventing one. {_STYLE_NOTE}"
)


def build_dissent_prompt(question: str, opinions: dict[str, str], label_map: dict[str, str], synthesis: str) -> str:
    reverse = {name: label for label, name in label_map.items()}
    parts = [f"Question:\n{question}\n", "Positions (by label):\n"]
    for name, text in opinions.items():
        parts.append(f"--- {reverse[name]} ---\n{text}\n")
    parts.append(f"\nFinal synthesised answer:\n{synthesis}\n")
    parts.append("\nWrite the dissent ledger now.")
    return "\n".join(parts)


async def run_dissent_stage(
    chair: Member,
    question: str,
    opinions: dict[str, str],
    member_names: list[str],
    synthesis: str,
    *,
    provider_for,
    max_tokens: int,
    calls: list[CallRecord],
) -> str:
    """Run stage 4: the chair writes the dissent ledger from an anonymised view."""
    label_map = build_global_label_map(member_names)
    prompt = build_dissent_prompt(question, opinions, label_map, synthesis)
    provider: Provider = provider_for(chair.provider)
    start = time.monotonic()
    completion = await provider.complete(
        system=_DISSENT_INSTRUCTION, user=prompt, model=chair.model, max_tokens=max_tokens, temperature=chair.temperature
    )
    calls.append(CallRecord("dissent", chair.name, time.monotonic() - start, completion.usage))
    return completion.text


# --------------------------------------------------------------------------
# Orchestration
# --------------------------------------------------------------------------


async def run_council(
    members: list[Member],
    question: str,
    *,
    chair_name: str,
    provider_for,
    rubric: list[str] | None = None,
    max_tokens: int = 1024,
    run_dissent: bool = True,
    run_seed: int | None = None,
) -> RunResult:
    """Run all four stages and return a RunResult ready for transcript.py."""
    if not members:
        raise ValueError("run_council needs at least one member")
    members_by_name = {m.name: m for m in members}
    if chair_name not in members_by_name:
        raise ValueError(f"chair {chair_name!r} is not one of the configured members: {list(members_by_name)}")

    rubric = rubric or DEFAULT_RUBRIC
    seed = run_seed if run_seed is not None else abs(hash(question)) & 0xFFFFFFFF
    calls: list[CallRecord] = []

    opinions = await run_opinion_stage(members, question, provider_for=provider_for, max_tokens=max_tokens, calls=calls)

    if len(members) > 1:
        reviews = await run_review_stage(
            members, question, opinions, provider_for=provider_for, rubric=rubric,
            max_tokens=max_tokens, run_seed=seed, calls=calls,
        )
    else:
        reviews = []

    chair = members_by_name[chair_name]
    synthesis = await run_synthesis_stage(
        chair, question, opinions, reviews, provider_for=provider_for, max_tokens=max_tokens, calls=calls
    )

    dissent = ""
    if run_dissent and len(members) > 1:
        dissent = await run_dissent_stage(
            chair, question, opinions, [m.name for m in members], synthesis,
            provider_for=provider_for, max_tokens=max_tokens, calls=calls,
        )

    return RunResult(
        question=question, members=members, chair=chair_name, opinions=opinions,
        reviews=reviews, synthesis=synthesis, dissent=dissent, calls=calls,
    )
