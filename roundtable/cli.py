"""The `roundtable` command.

    roundtable ask "question" [--config council.yaml] [--members a,b,c] [--chair x]
                               [--lenses cfo,operator] [--dry-run] [--no-dissent] [--out runs/]
    roundtable leaderboard [--path leaderboard.json]
    roundtable show <run-name-or-path>

No framework dependency here on purpose: argparse plus plain print. Run
`roundtable ask --help` for the full flag list.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

import yaml

from . import council
from .lenses import assign_lenses
from .providers import ProviderError, get_provider
from .transcript import leaderboard_rows, load_leaderboard, update_leaderboard, write_run

DEFAULT_CONFIG = "council.yaml"
DEFAULT_LEADERBOARD = "leaderboard.json"
DEFAULT_OUT = "runs"


def load_dotenv(path: str | Path = ".env") -> None:
    """Minimal .env loader: KEY=VALUE per line, no external dependency.

    Never overwrites a variable already set in the environment, so a real
    shell export always wins over the file. Silently does nothing if the
    file is absent: .env is optional, not required.
    """
    path = Path(path)
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def load_config(path: str | Path) -> dict:
    path = Path(path)
    if not path.is_file():
        raise SystemExit(
            f"No config at {path}. Copy council.yaml.example to {path} and fill in your members, "
            "or pass --config to point at a different file."
        )
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def build_members(config: dict, only_names: list[str] | None, lens_names: list[str] | None) -> list[council.Member]:
    all_members = config.get("members", [])
    if not all_members:
        raise SystemExit("council.yaml has no members configured.")

    if only_names:
        by_name = {m["name"]: m for m in all_members}
        missing = [n for n in only_names if n not in by_name]
        if missing:
            raise SystemExit(f"--members named unknown member(s): {missing}. Configured: {list(by_name)}")
        selected = [by_name[n] for n in only_names]
    else:
        selected = all_members

    lens_assignment: dict[str, str] = {}
    if lens_names:
        lens_dir = config.get("lens_dir", "lenses")
        lens_assignment = assign_lenses([m["name"] for m in selected], lens_names, lens_dir)

    members = []
    for m in selected:
        members.append(
            council.Member(
                name=m["name"],
                provider=m["provider"],
                model=m["model"],
                temperature=m.get("temperature", 0.7),
                lens=lens_assignment.get(m["name"], ""),
            )
        )
    return members


def _provider_for_factory(dry_run: bool):
    if dry_run:
        fake = get_provider("fake")
        return lambda _name: fake
    return get_provider


async def _run_ask(args: argparse.Namespace) -> None:
    load_dotenv()
    config = load_config(args.config)

    only_names = args.members.split(",") if args.members else None
    lens_names = args.lenses.split(",") if args.lenses else None
    members = build_members(config, only_names, lens_names)

    chair_name = args.chair or config.get("chair")
    if not chair_name:
        raise SystemExit("No chair configured. Set `chair:` in council.yaml or pass --chair.")

    rubric = config.get("review_rubric", council.DEFAULT_RUBRIC)
    max_tokens = config.get("max_tokens", 1024)
    run_dissent = config.get("dissent", True) and not args.no_dissent

    provider_for = _provider_for_factory(args.dry_run)

    print(f"Asking {len(members)} member(s): {', '.join(m.name for m in members)} (chair: {chair_name})")
    if args.dry_run:
        print("(--dry-run: using the fake provider, no network calls will be made)")

    result = await council.run_council(
        members, args.question, chair_name=chair_name, provider_for=provider_for,
        rubric=rubric, max_tokens=max_tokens, run_dissent=run_dissent,
    )

    md_path, json_path = write_run(result, args.out)
    print(f"\nWrote transcript: {md_path}")
    print(f"Wrote sidecar:    {json_path}")

    if result.reviews and not args.dry_run:
        board_path = config.get("leaderboard_path", DEFAULT_LEADERBOARD)
        update_leaderboard(board_path, result)
        print(f"Updated leaderboard: {board_path}")

    total_in = sum(c.usage.input_tokens for c in result.calls)
    total_out = sum(c.usage.output_tokens for c in result.calls)
    total_cost = sum(c.usage.cost_usd for c in result.calls)
    cost_note = f" (${total_cost:.4f})" if total_cost else ""
    print(f"\nTokens: {total_in} in / {total_out} out across {len(result.calls)} calls.{cost_note}")
    print(f"\n{'=' * 72}\nFinal answer:\n{'=' * 72}\n{result.synthesis}")


def _cmd_leaderboard(args: argparse.Namespace) -> None:
    board = load_leaderboard(args.path)
    rows = leaderboard_rows(board)
    if not rows:
        print(f"No leaderboard data yet at {args.path}. Run `roundtable ask` (not --dry-run) at least once.")
        return
    print(f"{'model':<20} {'mean rank':>10} {'wins':>6} {'reviews':>8} {'runs':>6}")
    for row in rows:
        mean_rank = f"{row['mean_rank']:.2f}" if row["mean_rank"] is not None else "-"
        print(f"{row['model']:<20} {mean_rank:>10} {row['wins']:>6} {row['reviews_received']:>8} {row['runs']:>6}")


def _cmd_show(args: argparse.Namespace) -> None:
    path = Path(args.run)
    if not path.exists():
        candidate = Path(DEFAULT_OUT) / f"{args.run}.md"
        if candidate.exists():
            path = candidate
        else:
            raise SystemExit(f"No run found at {args.run} or {candidate}")
    print(path.read_text(encoding="utf-8"))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="roundtable", description="Ask a council of LLMs instead of one.")
    sub = parser.add_subparsers(dest="command", required=True)

    ask = sub.add_parser("ask", help="Pose a question to the council.")
    ask.add_argument("question")
    ask.add_argument("--config", default=DEFAULT_CONFIG, help=f"Path to council.yaml (default: {DEFAULT_CONFIG})")
    ask.add_argument("--members", help="Comma-separated subset of configured member names, in order.")
    ask.add_argument("--chair", help="Override the configured chair with this member name.")
    ask.add_argument("--lenses", help="Comma-separated lens names, assigned to members in order.")
    ask.add_argument("--dry-run", action="store_true", help="Use the fake provider; no network calls, no cost.")
    ask.add_argument("--no-dissent", action="store_true", help="Skip stage 4, the dissent ledger.")
    ask.add_argument("--out", default=DEFAULT_OUT, help=f"Output directory for transcripts (default: {DEFAULT_OUT})")
    ask.set_defaults(func=lambda a: asyncio.run(_run_ask(a)))

    leaderboard = sub.add_parser("leaderboard", help="Show the cumulative peer-review leaderboard.")
    leaderboard.add_argument("--path", default=DEFAULT_LEADERBOARD)
    leaderboard.set_defaults(func=_cmd_leaderboard)

    show = sub.add_parser("show", help="Print a saved transcript by name or path.")
    show.add_argument("run")
    show.set_defaults(func=_cmd_show)

    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        args.func(args)
    except ProviderError as exc:
        print(f"Provider error: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
