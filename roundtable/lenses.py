"""Lens loading: turn a lens name into a system-prompt preamble.

A lens is a short markdown file that gives a member a point of view (what it
always asks, what it distrusts, how it wants the answer shaped) so the
council argues from different vantage points rather than just different
model weights. Lenses are plain text: no frontmatter parsing, no schema,
just a file whose contents get prepended to a member's system prompt. See
lenses/cfo.md, lenses/operator.md, lenses/sceptic.md for the three shipped
with this repo, and the README's "adapting it" section for writing your own.
"""

from __future__ import annotations

from pathlib import Path


def load_lens(name: str, lens_dir: str | Path) -> str:
    """Read `<lens_dir>/<name>.md` and return its contents.

    Raises FileNotFoundError with a clear message if the lens does not
    exist, since a typo in --lenses should fail loudly rather than silently
    running that member with no lens at all.
    """
    path = Path(lens_dir) / f"{name}.md"
    if not path.is_file():
        raise FileNotFoundError(
            f"Lens {name!r} not found at {path}. Available lenses: "
            f"{', '.join(sorted(p.stem for p in Path(lens_dir).glob('*.md')))}"
        )
    return path.read_text(encoding="utf-8").strip()


def assign_lenses(member_names: list[str], lens_names: list[str], lens_dir: str | Path) -> dict[str, str]:
    """Assign lenses to members 1:1, in order.

    Extra members beyond the lens count get no lens (empty string). Extra
    lenses beyond the member count are ignored. This is a simple positional
    match, not a smart pairing: put the lens you want a given member to
    carry in the matching position of --lenses.
    """
    assignment: dict[str, str] = {}
    for i, name in enumerate(member_names):
        assignment[name] = load_lens(lens_names[i], lens_dir) if i < len(lens_names) else ""
    return assignment
