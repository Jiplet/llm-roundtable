"""Stage 2 anonymisation: per-reviewer shuffle, self excluded, stable labels within a review."""

from roundtable.council import build_shuffle_map


def test_self_excluded():
    members = ["claude", "gpt", "llama"]
    label_map = build_shuffle_map("claude", members, seed=1)
    assert "claude" not in label_map.values()
    assert set(label_map.values()) == {"gpt", "llama"}


def test_labels_are_contiguous_from_a():
    members = ["claude", "gpt", "llama", "mistral"]
    label_map = build_shuffle_map("claude", members, seed=1)
    assert set(label_map.keys()) == {"A", "B", "C"}


def test_stable_within_a_review_same_seed():
    members = ["claude", "gpt", "llama"]
    first = build_shuffle_map("claude", members, seed=42)
    second = build_shuffle_map("claude", members, seed=42)
    assert first == second


def test_per_reviewer_shuffle_can_differ():
    # Not a strict requirement that they always differ (a coin flip could match by chance
    # for two members), but with enough members and different seeds, the maps should not
    # always be identical. This documents the property, not just asserts one sample.
    members = ["claude", "gpt", "llama", "mistral", "gemini"]
    seeds = range(20)
    maps = [build_shuffle_map("claude", members, seed=s) for s in seeds]
    assert len({tuple(sorted(m.items())) for m in maps}) > 1


def test_every_other_member_gets_exactly_one_label():
    members = ["claude", "gpt", "llama"]
    label_map = build_shuffle_map("gpt", members, seed=7)
    assert sorted(label_map.values()) == sorted(["claude", "llama"])
    assert len(label_map) == len(set(label_map.values()))
