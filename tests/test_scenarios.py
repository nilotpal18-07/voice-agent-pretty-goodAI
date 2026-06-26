"""Tests for the patient scenario library and its wiring into the agent.

All deterministic — no LLM calls, so these are fast and quota-free.
"""

from __future__ import annotations

import importlib
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

import caller.agent as agent_mod
from scenarios.scenarios import (
    DEFAULT_SCENARIO_ID,
    INVARIANT_ROLE_RULES,
    PatientScenario,
    SCENARIOS,
    build_instructions,
    get_scenario,
)

EXPECTED_IDS = {
    "scheduling",
    "reschedule",
    "refill",
    "info",
    "existing_patient_persistent",
    "out_of_scope",
}

# No-receptionist invariants that must survive in EVERY scenario's instructions.
INVARIANT_PHRASES = (
    "you are the caller",
    "you are not the receptionist",
    "thanks for calling",
    "how can i help you",
    "do not speak first",
    "automated notice",
)


def _norm(text: str) -> str:
    """Lowercase + collapse whitespace so phrase checks ignore line wrapping."""
    return " ".join(text.split()).lower()


def _valid_kwargs(**overrides) -> dict:
    base = dict(
        id="ok",
        title="t",
        persona="p",
        goal="g",
        key_facts={"name": "x"},
        behavior_notes=["n"],
        success_criteria="s",
        end_when="e",
    )
    base.update(overrides)
    return base


# --- Library shape ----------------------------------------------------------

def test_library_has_exactly_the_expected_scenarios() -> None:
    assert set(SCENARIOS) == EXPECTED_IDS
    assert DEFAULT_SCENARIO_ID in SCENARIOS


def test_registry_key_matches_scenario_id() -> None:
    for key, scenario in SCENARIOS.items():
        assert key == scenario.id


def test_all_ids_are_filename_safe() -> None:
    import re

    for sid in SCENARIOS:
        assert re.fullmatch(r"[a-z0-9_]+", sid), sid


def test_get_scenario_unknown_raises() -> None:
    with pytest.raises(KeyError):
        get_scenario("does_not_exist")


def test_id_validator_rejects_unsafe_ids() -> None:
    with pytest.raises(ValidationError):
        PatientScenario(**_valid_kwargs(id="Bad-Id"))  # capitals + hyphen
    with pytest.raises(ValidationError):
        PatientScenario(**_valid_kwargs(id="has space"))


def test_id_validator_accepts_safe_ids() -> None:
    assert PatientScenario(**_valid_kwargs(id="refill_v2")).id == "refill_v2"


# --- build_instructions -----------------------------------------------------

@pytest.mark.parametrize("sid", sorted(EXPECTED_IDS))
def test_every_scenario_builds_valid_instructions(sid: str) -> None:
    scenario = get_scenario(sid)
    instr = build_instructions(scenario)

    assert isinstance(instr, str) and len(instr) > 300
    # Scenario specifics are present...
    assert scenario.goal.strip() in instr
    assert scenario.persona.strip() in instr
    for value in scenario.key_facts.values():
        assert value in instr, f"missing fact {value!r} in {sid} instructions"
    for note in scenario.behavior_notes:
        assert note in instr, f"missing behavior note in {sid} instructions"
    # ...and the agent's hang-up tools are referenced.
    assert "end_call" in instr
    assert "detected_answering_machine" in instr


@pytest.mark.parametrize("sid", sorted(EXPECTED_IDS))
def test_invariant_role_rules_survive_for_every_scenario(sid: str) -> None:
    instr = build_instructions(get_scenario(sid))
    # The whole invariant block is present verbatim...
    assert INVARIANT_ROLE_RULES in instr
    # ...and each key no-receptionist phrase is too.
    normalized = _norm(instr)
    for phrase in INVARIANT_PHRASES:
        assert phrase in normalized, f"{sid} instructions dropped invariant: {phrase!r}"


def test_out_of_scope_patient_asks_about_sunday_not_announces_closure() -> None:
    """Regression: the out_of_scope patient must ASK about Sunday as a caller and never
    announce the clinic's hours/closures. A prior run had the bot say
    'I'm sorry, we're closed on Sundays' — inverting into the clinic's role."""
    low = " ".join(build_instructions(get_scenario("out_of_scope")).split()).lower()

    # Asks about Sunday as a request, and reacts as a caller if told it's closed.
    assert "can i come in this sunday" in low
    assert "what about monday then" in low

    # Explicitly forbidden from announcing the clinic's hours/closures.
    assert "never announce" in low
    assert "you are the caller, not the clinic" in low

    # The old, leak-prone goal framing ("a day the clinic is closed") is gone.
    assert "a day the clinic is closed" not in low


# --- Wiring into the agent (scenario id -> transcript filename) -------------

def test_default_scenario_id_is_scheduling(monkeypatch) -> None:
    monkeypatch.delenv("SCENARIO_ID", raising=False)
    reloaded = importlib.reload(agent_mod)
    try:
        assert reloaded.SCENARIO_ID == "scheduling"
        assert reloaded.SCENARIO.id == "scheduling"
    finally:
        importlib.reload(agent_mod)


def test_scenario_id_env_flows_to_transcript_filename(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("SCENARIO_ID", "refill")
    reloaded = importlib.reload(agent_mod)
    try:
        # env var -> selected scenario -> instructions
        assert reloaded.SCENARIO_ID == "refill"
        assert reloaded.SCENARIO.id == "refill"
        assert "lisinopril" in reloaded.PATIENT_INSTRUCTIONS  # a refill-specific fact

        # ...and the scenario id is what the transcript label uses.
        label = reloaded.next_call_label(reloaded.SCENARIO.id, tmp_path)
        assert label == "call-01-refill"
        assert (tmp_path / "call-01-refill.txt").exists()
    finally:
        monkeypatch.delenv("SCENARIO_ID", raising=False)
        importlib.reload(agent_mod)  # restore default for other tests


# --- Scenario selection precedence (dispatch metadata > env > default) -------

def test_resolve_scenario_id_prefers_metadata() -> None:
    metadata = json.dumps({"scenario_id": "refill"})
    assert agent_mod.resolve_scenario_id(metadata, "scheduling") == "refill"


def test_resolve_scenario_id_falls_back_to_env_without_metadata() -> None:
    assert agent_mod.resolve_scenario_id(None, "reschedule") == "reschedule"
    assert agent_mod.resolve_scenario_id("", "reschedule") == "reschedule"


def test_resolve_scenario_id_falls_back_to_default() -> None:
    assert agent_mod.resolve_scenario_id(None, None) == agent_mod.DEFAULT_SCENARIO_ID


def test_resolve_scenario_id_ignores_bad_or_incomplete_metadata() -> None:
    # Unparseable JSON -> env, then default.
    assert agent_mod.resolve_scenario_id("not json", "info") == "info"
    # Valid JSON but no scenario_id key -> env.
    assert agent_mod.resolve_scenario_id(json.dumps({"foo": "bar"}), "info") == "info"
    # Valid JSON, no scenario_id, no env -> default.
    assert (
        agent_mod.resolve_scenario_id(json.dumps({"foo": "bar"}), None)
        == agent_mod.DEFAULT_SCENARIO_ID
    )
