"""Tests for the batch runner's pure helpers (plan building, transcript scanning).

Network/dispatch behavior isn't exercised here — these cover the local logic that
decides what to run and how transcripts are flagged. No LLM calls.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from caller import batch_runner as br


def test_build_plan_default_is_two_per_scenario() -> None:
    plan = br.build_plan(None, repeat=2)
    # 6 scenarios x 2 = 12 calls, each scenario appearing exactly twice.
    assert len(plan) == 12
    for sid in br.SCENARIOS:
        assert plan.count(sid) == 2


def test_build_plan_respects_repeat() -> None:
    assert len(br.build_plan(None, repeat=1)) == len(br.SCENARIOS)
    assert len(br.build_plan(None, repeat=3)) == len(br.SCENARIOS) * 3


def test_build_plan_custom_counts() -> None:
    plan = br.build_plan("scheduling=3,refill=2,info=1", repeat=2)
    assert plan.count("scheduling") == 3
    assert plan.count("refill") == 2
    assert plan.count("info") == 1
    assert len(plan) == 6


def test_build_plan_bare_scenario_defaults_to_one() -> None:
    plan = br.build_plan("scheduling,refill=2", repeat=5)
    assert plan.count("scheduling") == 1
    assert plan.count("refill") == 2


def test_build_plan_rejects_unknown_scenario() -> None:
    with pytest.raises(SystemExit):
        br.build_plan("nope=2", repeat=2)


def test_transcript_turns_counts_only_conversation_lines(tmp_path: Path) -> None:
    p = tmp_path / "call-01-scheduling.txt"
    p.write_text(
        "# Transcript - call-01-scheduling\n"
        "# Room: room-x\n"
        "\n"
        "AGENT (clinic): Hello?\n"
        "PATIENT (bot): Hi, I'd like to book a check-up.\n"
        "AGENT (clinic): Sure.\n",
        encoding="utf-8",
    )
    assert br._transcript_turns(p) == 3


def test_transcript_turns_zero_for_header_only_stub(tmp_path: Path) -> None:
    p = tmp_path / "call-02-scheduling.txt"
    p.write_text("# Transcript - call-02-scheduling\n# Room: room-y\n\n", encoding="utf-8")
    assert br._transcript_turns(p) == 0


def test_call_result_stub_flag() -> None:
    # A transcript that exists but has no turns is a stub.
    stub = br.CallResult(index=1, scenario_id="scheduling", room="r", transcript="call-01-scheduling.txt", turns=0)
    assert stub.stub is True
    # A transcript with turns is not a stub.
    real = br.CallResult(index=2, scenario_id="scheduling", room="r", transcript="call-02-scheduling.txt", turns=6)
    assert real.stub is False
    # No transcript at all is not flagged as a stub.
    none = br.CallResult(index=3, scenario_id="scheduling", room="r", transcript=None, turns=0)
    assert none.stub is False
