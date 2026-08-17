"""Stage 2 parsing: well-formed reviewer output and sloppy, off-format output."""

from roundtable.council import DEFAULT_RUBRIC, parse_review


WELL_FORMED = """
## Response A
Accuracy: 8/10
Insight: 6/10
Completeness: 7/10
Notes: Specific and checkable.

## Response B
Accuracy: 5/10
Insight: 9/10
Completeness: 4/10
Notes: Interesting but unproven.

RANKING: A > B
REASONING: A is more testable even though B is more original.
"""

SLOPPY_NO_RANKING_LINE = """
Response A scored well: Accuracy: 9/10, Insight: 7/10, Completeness: 8/10.
Response B was weaker: Accuracy: 4/10, Insight: 5/10, Completeness: 5/10.
I think A is clearly the better answer overall.
"""

UNSTRUCTURED_FREEFORM = """
Honestly both answers were fine, hard to pick a favourite, they cover different angles
and neither one nails it completely so I would call it a toss-up between them.
"""


def test_well_formed_parses_scores_and_ranking():
    result = parse_review(WELL_FORMED, valid_labels=["A", "B"])
    assert not result.fallback_used
    assert result.ranking == ["A", "B"]
    assert result.reasoning.startswith("A is more testable")
    scores_by_label = {s.label: s.scores for s in result.scores}
    assert scores_by_label["A"] == {"accuracy": 8, "insight": 6, "completeness": 7}
    assert scores_by_label["B"] == {"accuracy": 5, "insight": 9, "completeness": 4}


def test_sloppy_missing_ranking_line_falls_back_to_scores():
    result = parse_review(SLOPPY_NO_RANKING_LINE, valid_labels=["A", "B"], rubric=DEFAULT_RUBRIC)
    assert result.fallback_used
    # No "## Response X" headers means no structured scores get parsed either; the
    # fallback still produces a complete, valid ranking rather than crashing.
    assert set(result.ranking) == {"A", "B"}


def test_unstructured_freeform_still_returns_a_full_ranking():
    result = parse_review(UNSTRUCTURED_FREEFORM, valid_labels=["A", "B", "C"])
    assert result.fallback_used
    assert set(result.ranking) == {"A", "B", "C"}
    assert len(result.ranking) == 3


def test_ranking_line_with_extra_prose_still_parses():
    text = "RANKING: I would put it as A > C > B, roughly.\nREASONING: gut call."
    result = parse_review(text, valid_labels=["A", "B", "C"])
    assert result.ranking == ["A", "C", "B"]
    assert not result.fallback_used


def test_scores_with_missing_dimension_are_partial_not_crashing():
    text = "## Response A\nAccuracy: 7/10\nNotes: no insight score given.\n\nRANKING: A"
    result = parse_review(text, valid_labels=["A"], rubric=DEFAULT_RUBRIC)
    assert result.scores[0].scores == {"accuracy": 7}
