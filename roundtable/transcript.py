"""Write a run to disk: a readable markdown transcript, a JSON sidecar, and
an updated leaderboard.

The markdown file is the thing a human reads: question, the four stages in
order, then a timing/token table. The JSON sidecar carries the same data in
a shape a script can consume (label maps, per-response scores, raw model
text) without having to re-parse markdown. leaderboard.json is a small,
cumulative file: every run's peer rankings get folded into a running mean
rank position per model, so `roundtable leaderboard` can answer "which
model do my other models keep preferring" across every run you have made,
not just the last one.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from .council import CallRecord, RunResult


def _slug(question: str, limit: int = 40) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", question.lower()).strip("-")
    return slug[:limit].rstrip("-") or "question"


def run_basename(question: str, when: datetime | None = None) -> str:
    when = when or datetime.now()
    return f"{when.strftime('%Y-%m-%d-%H%M')}-{_slug(question)}"


def _usage_table(calls: list[CallRecord]) -> tuple[str, int, int, float]:
    any_cost = any(call.usage.cost_usd for call in calls)
    header = "| stage | member | elapsed (s) | input tokens | output tokens |"
    sep = "|---|---|---|---|---|"
    if any_cost:
        header += " cost (USD) |"
        sep += "---|"
    lines = [header, sep]
    total_in = total_out = 0
    total_cost = 0.0
    for call in calls:
        row = (
            f"| {call.stage} | {call.member} | {call.elapsed_s:.2f} | "
            f"{call.usage.input_tokens} | {call.usage.output_tokens} |"
        )
        if any_cost:
            row += f" {call.usage.cost_usd:.4f} |"
        lines.append(row)
        total_in += call.usage.input_tokens
        total_out += call.usage.output_tokens
        total_cost += call.usage.cost_usd
    total_row = f"| **total** | | | **{total_in}** | **{total_out}** |"
    if any_cost:
        total_row += f" **{total_cost:.4f}** |"
    lines.append(total_row)
    return "\n".join(lines), total_in, total_out, total_cost


def render_markdown(result: RunResult) -> str:
    """Render a RunResult as a readable markdown transcript."""
    lines: list[str] = []
    lines.append(f"# Roundtable: {result.question}")
    lines.append("")
    lines.append(f"**Members:** {', '.join(f'{m.name} ({m.provider}/{m.model})' for m in result.members)}")
    lines.append(f"**Chair:** {result.chair}")
    lines.append("")

    lines.append("## Stage 1: first opinions")
    for name, text in result.opinions.items():
        lines.append(f"\n### {name}\n\n{text}")

    if result.reviews:
        lines.append("\n## Stage 2: anonymised peer review")
        lines.append(
            "\nEach reviewer saw the other members' answers under a private, per-reviewer "
            "label shuffle. Labels below are resolved back to real names after the fact."
        )
        for review in result.reviews:
            lines.append(f"\n### {review.reviewer}'s review")
            if review.fallback_used:
                lines.append("\n_Ranking could not be fully parsed from the model's own words; a fallback rule was used._")
            for score in review.scores:
                real_name = review.label_map.get(score.label, score.label)
                score_str = ", ".join(f"{dim}: {val}/10" for dim, val in score.scores.items())
                lines.append(f"\n- **{score.label}** ({real_name}): {score_str or 'no scores parsed'}")
                if score.notes:
                    lines.append(f"  Notes: {score.notes}")
            ranking = " > ".join(review.resolved_ranking) or "(unresolved)"
            lines.append(f"\n**Ranking:** {ranking}")
            if review.reasoning:
                lines.append(f"**Reasoning:** {review.reasoning}")

    lines.append("\n## Stage 3: chair synthesis")
    lines.append(f"\n{result.synthesis}")

    if result.dissent:
        lines.append("\n## Stage 4: dissent ledger")
        lines.append(f"\n{result.dissent}")

    lines.append("\n## Run metadata")
    table, total_in, total_out, total_cost = _usage_table(result.calls)
    lines.append(f"\n{table}")
    cost_note = f" Total cost: ${total_cost:.4f}." if total_cost else ""
    lines.append(f"\nTotal tokens: {total_in} in / {total_out} out.{cost_note}")

    return "\n".join(lines) + "\n"


def _result_to_json(result: RunResult) -> dict:
    return {
        "question": result.question,
        "members": [asdict(m) for m in result.members],
        "chair": result.chair,
        "opinions": result.opinions,
        "reviews": [
            {
                "reviewer": r.reviewer,
                "label_map": r.label_map,
                "scores": [asdict(s) for s in r.scores],
                "ranking": r.ranking,
                "resolved_ranking": r.resolved_ranking,
                "reasoning": r.reasoning,
                "fallback_used": r.fallback_used,
                "raw": r.raw,
            }
            for r in result.reviews
        ],
        "synthesis": result.synthesis,
        "dissent": result.dissent,
        "calls": [
            {"stage": c.stage, "member": c.member, "elapsed_s": c.elapsed_s,
             "input_tokens": c.usage.input_tokens, "output_tokens": c.usage.output_tokens,
             "cost_usd": c.usage.cost_usd}
            for c in result.calls
        ],
    }


def write_run(result: RunResult, out_dir: str | Path, when: datetime | None = None) -> tuple[Path, Path]:
    """Write the markdown transcript and JSON sidecar. Returns (md_path, json_path)."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    base = run_basename(result.question, when=when)
    md_path = out_dir / f"{base}.md"
    json_path = out_dir / f"{base}.json"
    md_path.write_text(render_markdown(result), encoding="utf-8")
    json_path.write_text(json.dumps(_result_to_json(result), indent=2), encoding="utf-8")
    return md_path, json_path


# --------------------------------------------------------------------------
# Leaderboard
# --------------------------------------------------------------------------


def _empty_leaderboard() -> dict:
    return {"models": {}, "updated": None}


def load_leaderboard(path: str | Path) -> dict:
    path = Path(path)
    if not path.is_file():
        return _empty_leaderboard()
    return json.loads(path.read_text(encoding="utf-8"))


def update_leaderboard(path: str | Path, result: RunResult) -> dict:
    """Fold one run's peer rankings into the cumulative leaderboard and save it.

    Per model: `runs` counts how many roundtables it took part in (once per
    run, regardless of how many reviewers scored it); `reviews_received`
    counts how many individual reviews ranked it; `rank_sum` accumulates its
    rank position (1 = ranked best) from every review it appeared in, so
    `mean_rank` (rank_sum / reviews_received) is comparable across models
    that have been reviewed different numbers of times; `wins` counts how
    often a reviewer ranked it first. Lower mean_rank is better. See the
    README design notes for why mean rank position is used instead of a raw
    win count.
    """
    board = load_leaderboard(path)
    models = board["models"]

    member_names = [m.name for m in result.members]
    for name in member_names:
        models.setdefault(name, {"runs": 0, "reviews_received": 0, "rank_sum": 0, "wins": 0})
        models[name]["runs"] += 1

    for review in result.reviews:
        for position, name in enumerate(review.resolved_ranking, start=1):
            entry = models.setdefault(name, {"runs": 0, "reviews_received": 0, "rank_sum": 0, "wins": 0})
            entry["reviews_received"] += 1
            entry["rank_sum"] += position
            if position == 1:
                entry["wins"] += 1

    board["updated"] = datetime.now(timezone.utc).isoformat()
    Path(path).write_text(json.dumps(board, indent=2), encoding="utf-8")
    return board


def leaderboard_rows(board: dict) -> list[dict]:
    """Leaderboard as a list of rows sorted by mean rank (best first), for display."""
    rows = []
    for name, entry in board.get("models", {}).items():
        received = entry.get("reviews_received", 0)
        mean_rank = (entry["rank_sum"] / received) if received else None
        rows.append({"model": name, "mean_rank": mean_rank, "wins": entry.get("wins", 0),
                      "reviews_received": received, "runs": entry.get("runs", 0)})
    rows.sort(key=lambda r: (r["mean_rank"] is None, r["mean_rank"] if r["mean_rank"] is not None else 0))
    return rows
