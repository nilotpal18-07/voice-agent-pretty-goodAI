"""Deterministic tests for the analysis harness.

Covers transcript parsing, defensive JSON extraction, response normalization, and
the dedup/aggregation/ranking logic.
"""

from __future__ import annotations

from pathlib import Path

import json

from analysis.analyze import (
    CallAnalysis,
    Finding,
    aggregate_bugs,
    build_call_analysis,
    extract_json,
    goal_summary,
    load_cached_per_call,
    parse_transcript,
    rank_bugs,
    scenario_id_from_name,
)


# --- Parsing ----------------------------------------------------------------

def test_scenario_id_from_name_handles_underscored_scenarios() -> None:
    assert scenario_id_from_name("call-01-scheduling.txt") == "scheduling"
    assert scenario_id_from_name("call-12-existing_patient_persistent.txt") == "existing_patient_persistent"
    assert scenario_id_from_name("weird.txt") == "unknown"


def test_parse_transcript_extracts_turns(tmp_path: Path) -> None:
    p = tmp_path / "call-01-scheduling.txt"
    p.write_text(
        "# Transcript - call-01-scheduling\n"
        "# Room: room-x\n"
        "\n"
        "AGENT (clinic): This call may be recorded.\n"
        "PATIENT (bot): Hi, I'd like to book a check-up.\n"
        "AGENT (clinic): Sure thing.\n",
        encoding="utf-8",
    )
    tx = parse_transcript(p)
    assert tx.scenario_id == "scheduling"
    assert not tx.is_stub
    assert [t.speaker for t in tx.turns] == ["agent", "patient", "agent"]
    assert tx.turns[1].text == "Hi, I'd like to book a check-up."
    assert tx.turns[0].lineno == 4  # line numbers preserved for grounding


def test_parse_transcript_stub_has_no_turns(tmp_path: Path) -> None:
    p = tmp_path / "call-09-refill.txt"
    p.write_text("# Transcript - call-09-refill\n# Room: room-y\n\n", encoding="utf-8")
    tx = parse_transcript(p)
    assert tx.is_stub
    assert tx.turns == []


# --- Defensive JSON ---------------------------------------------------------

def test_extract_json_plain() -> None:
    assert extract_json('{"a": 1}') == {"a": 1}


def test_extract_json_strips_code_fences() -> None:
    assert extract_json('```json\n{"a": 1}\n```') == {"a": 1}


def test_extract_json_pulls_object_from_surrounding_prose() -> None:
    assert extract_json('Here you go:\n{"a": 1}\nThanks!') == {"a": 1}


# --- Response normalization -------------------------------------------------

def test_build_call_analysis_normalizes_and_aliases() -> None:
    data = {
        "goal_outcome": {"verdict": "FAIL", "reason": "no booking"},
        "findings": [
            {"category": "Date of Birth Hallucination", "description": "invented DOB",
             "severity": "critical", "evidence": "your date of birth is July fourth two thousand"},
            {"category": "weird_new_thing", "description": "x", "severity": "bogus", "evidence": "q"},
        ],
    }
    ca = build_call_analysis("call-01-scheduling.txt", "scheduling", data)
    assert ca.goal_verdict == "fail"
    # alias folded onto the seed id; severity title-cased.
    assert ca.findings[0].category == "dob_hallucination"
    assert ca.findings[0].severity == "Critical"
    # unknown category kept (normalized); unknown severity defaults to Minor.
    assert ca.findings[1].category == "weird_new_thing"
    assert ca.findings[1].severity == "Minor"


def test_build_call_analysis_handles_missing_fields() -> None:
    ca = build_call_analysis("call-01-info.txt", "info", {})
    assert ca.goal_verdict == "unknown"
    assert ca.findings == []


# --- Aggregation / dedup / ranking ------------------------------------------

def _ca(name, scenario, verdict, findings):
    return CallAnalysis(name, scenario, verdict, "reason", findings)


def test_aggregate_dedupes_by_category_and_counts_distinct_transcripts() -> None:
    per_call = [
        _ca("call-01-scheduling.txt", "scheduling", "fail", [
            Finding("dob_hallucination", "invented dob", "Major", "q1"),
        ]),
        _ca("call-02-scheduling.txt", "scheduling", "fail", [
            Finding("dob_hallucination", "invented dob again", "Critical", "q2"),
            Finding("dob_hallucination", "same call dup", "Minor", "q2b"),  # same transcript
        ]),
        _ca("call-01-refill.txt", "refill", "pass", [
            Finding("broken_transfer", "dead end", "Critical", "q3"),
        ]),
    ]
    bugs = aggregate_bugs(per_call, analyzed=3)
    by_id = {b.id: b for b in bugs}

    dob = by_id["dob_hallucination"]
    # distinct transcripts only (call-02 had two findings but counts once)
    assert dob.count == 2
    assert dob.reproduction == "2/3"
    assert dob.sources == ["call-01-scheduling.txt", "call-02-scheduling.txt"]
    # severity is the highest observed across the group
    assert dob.severity == "Critical"
    # seed category maps to its manual ref
    assert dob.manual_ref == "BUG-02"

    assert by_id["broken_transfer"].manual_ref == "BUG-08, BUG-13"


def test_aggregate_caps_examples_to_three_distinct_sources() -> None:
    findings_calls = [
        _ca(f"call-0{i}-scheduling.txt", "scheduling",
            "fail", [Finding("profile_loop", "loop", "Major", f"quote{i}")])
        for i in range(1, 6)  # 5 distinct transcripts
    ]
    bugs = aggregate_bugs(findings_calls, analyzed=5)
    loop = next(b for b in bugs if b.id == "profile_loop")
    assert loop.count == 5
    assert len(loop.examples) == 3  # capped
    assert len({ex["source"] for ex in loop.examples}) == 3  # distinct sources


def test_rank_orders_by_severity_then_count() -> None:
    per_call = [
        _ca("c1.txt", "s", "fail", [Finding("minor_thing", "m", "Minor", "q")]),
        _ca("c2.txt", "s", "fail", [Finding("crit_a", "a", "Critical", "q")]),
        _ca("c3.txt", "s", "fail", [Finding("crit_b", "b", "Critical", "q")]),
        _ca("c4.txt", "s", "fail", [Finding("crit_b", "b", "Critical", "q")]),  # crit_b in 2 calls
    ]
    bugs = rank_bugs(aggregate_bugs(per_call, analyzed=4))
    # Critical before Minor; within Critical, higher reproduction first.
    assert bugs[0].id == "crit_b"  # critical, count 2
    assert bugs[1].id == "crit_a"  # critical, count 1
    assert bugs[-1].id == "minor_thing"


def test_aliases_fold_new_synonym_clusters() -> None:
    data = {
        "goal_outcome": {"verdict": "fail", "reason": "r"},
        "findings": [
            {"category": "loss_of_context", "description": "d", "severity": "Major", "evidence": "e"},
            {"category": "existing_patient_lookup_failure", "description": "d", "severity": "Major", "evidence": "e"},
            {"category": "redundant_question", "description": "d", "severity": "Minor", "evidence": "e"},
        ],
    }
    ca = build_call_analysis("call-01-scheduling.txt", "scheduling", data)
    assert [f.category for f in ca.findings] == ["context_loss", "profile_loop", "redundant_prompts"]


def test_load_cached_per_call_refolds_aliases(tmp_path) -> None:
    fj = tmp_path / "findings.json"
    fj.write_text(
        json.dumps(
            {
                "model": "gemini-x",
                "skipped": [{"transcript": "call-09-refill.txt", "reason": "stub"}],
                "per_call": [
                    {
                        "transcript": "call-01-scheduling.txt",
                        "scenario_id": "scheduling",
                        "goal_outcome": {"verdict": "fail", "reason": "r"},
                        "findings": [
                            {"category": "loss_of_context", "description": "d",
                             "severity": "Major", "evidence": "e"}
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    per_call, skipped, model = load_cached_per_call(fj)
    assert model == "gemini-x"
    assert skipped == [{"transcript": "call-09-refill.txt", "reason": "stub"}]
    # category re-folded through the current alias map
    assert per_call[0].findings[0].category == "context_loss"


def test_goal_summary_counts_per_scenario() -> None:
    per_call = [
        _ca("a.txt", "scheduling", "pass", []),
        _ca("b.txt", "scheduling", "fail", []),
        _ca("c.txt", "scheduling", "partial", []),
        _ca("d.txt", "refill", "pass", []),
    ]
    summ = goal_summary(per_call)
    assert summ["scheduling"] == {"pass": 1, "partial": 1, "fail": 1, "unknown": 0, "total": 3}
    assert summ["refill"]["pass"] == 1
    assert summ["refill"]["total"] == 1
