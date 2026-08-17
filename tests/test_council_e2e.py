"""End-to-end council run against the fake provider: all four stages, transcript, leaderboard.

No network access needed: this is the test that --dry-run also exercises via the CLI,
just called directly against council.run_council here for a tighter assertion surface.
"""

import json

import pytest

from roundtable.council import Member, run_council
from roundtable.providers import get_provider, reset_providers
from roundtable.transcript import load_leaderboard, update_leaderboard, write_run


@pytest.fixture(autouse=True)
def _reset():
    reset_providers()
    yield
    reset_providers()


def _fake_provider_for(_name: str):
    return get_provider("fake")


@pytest.mark.asyncio
async def test_full_run_has_all_four_stages():
    members = [
        Member(name="claude", provider="fake", model="fake-claude"),
        Member(name="gpt", provider="fake", model="fake-gpt"),
    ]
    result = await run_council(members, "Should a small team adopt a monorepo?",
                                chair_name="claude", provider_for=_fake_provider_for)

    # Stage 1
    assert set(result.opinions) == {"claude", "gpt"}
    assert all(result.opinions.values())

    # Stage 2
    assert len(result.reviews) == 2
    reviewers = {r.reviewer for r in result.reviews}
    assert reviewers == {"claude", "gpt"}
    for review in result.reviews:
        assert review.reviewer not in review.label_map.values()
        assert review.resolved_ranking

    # Stage 3
    assert result.synthesis

    # Stage 4
    assert result.dissent


@pytest.mark.asyncio
async def test_no_dissent_flag_skips_stage_four():
    members = [
        Member(name="claude", provider="fake", model="fake-claude"),
        Member(name="gpt", provider="fake", model="fake-gpt"),
    ]
    result = await run_council(members, "Same question", chair_name="claude",
                                provider_for=_fake_provider_for, run_dissent=False)
    assert result.dissent == ""


@pytest.mark.asyncio
async def test_transcript_written_and_leaderboard_updated(tmp_path):
    members = [
        Member(name="claude", provider="fake", model="fake-claude"),
        Member(name="gpt", provider="fake", model="fake-gpt"),
        Member(name="mistral", provider="fake", model="fake-mistral"),
    ]
    result = await run_council(members, "Is a four-day week good for field services?",
                                chair_name="gpt", provider_for=_fake_provider_for)

    md_path, json_path = write_run(result, tmp_path)
    assert md_path.exists()
    assert json_path.exists()
    assert "Stage 1: first opinions" in md_path.read_text()
    assert "Stage 4: dissent ledger" in md_path.read_text()

    sidecar = json.loads(json_path.read_text())
    assert sidecar["chair"] == "gpt"
    assert len(sidecar["reviews"]) == 3

    board_path = tmp_path / "leaderboard.json"
    board = update_leaderboard(board_path, result)
    assert set(board["models"]) == {"claude", "gpt", "mistral"}
    for name in ("claude", "gpt", "mistral"):
        assert board["models"][name]["runs"] == 1
        assert board["models"][name]["reviews_received"] == 2  # ranked by the other two members

    reloaded = load_leaderboard(board_path)
    assert reloaded == board


@pytest.mark.asyncio
async def test_leaderboard_accumulates_across_runs(tmp_path):
    members = [
        Member(name="claude", provider="fake", model="fake-claude"),
        Member(name="gpt", provider="fake", model="fake-gpt"),
    ]
    board_path = tmp_path / "leaderboard.json"

    result1 = await run_council(members, "Question one", chair_name="claude", provider_for=_fake_provider_for)
    update_leaderboard(board_path, result1)
    result2 = await run_council(members, "Question two", chair_name="claude", provider_for=_fake_provider_for)
    board = update_leaderboard(board_path, result2)

    assert board["models"]["claude"]["runs"] == 2
    assert board["models"]["gpt"]["runs"] == 2


@pytest.mark.asyncio
async def test_single_member_run_skips_review_and_dissent():
    members = [Member(name="claude", provider="fake", model="fake-claude")]
    result = await run_council(members, "Solo question", chair_name="claude", provider_for=_fake_provider_for)
    assert result.reviews == []
    assert result.dissent == ""
    assert result.synthesis
