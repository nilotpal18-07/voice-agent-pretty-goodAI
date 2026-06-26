"""Unit tests for the auto-incrementing, non-overwriting call-label scheme.

Pure filesystem logic — no LLM calls, so these are fast and quota-free.
"""

from __future__ import annotations

from pathlib import Path

from caller.agent import next_call_label


def test_first_label_in_empty_dir(tmp_path: Path) -> None:
    assert next_call_label("scheduling", tmp_path) == "call-01-scheduling"
    # the slot is reserved on disk immediately
    assert (tmp_path / "call-01-scheduling.txt").exists()


def test_increments_past_highest_existing(tmp_path: Path) -> None:
    (tmp_path / "call-01-scheduling.txt").touch()
    (tmp_path / "call-02-scheduling.txt").touch()
    assert next_call_label("scheduling", tmp_path) == "call-03-scheduling"


def test_uses_highest_plus_one_even_with_gaps(tmp_path: Path) -> None:
    (tmp_path / "call-01-scheduling.txt").touch()
    (tmp_path / "call-05-scheduling.txt").touch()
    assert next_call_label("scheduling", tmp_path) == "call-06-scheduling"


def test_scenarios_are_numbered_independently(tmp_path: Path) -> None:
    (tmp_path / "call-01-scheduling.txt").touch()
    (tmp_path / "call-02-scheduling.txt").touch()
    # a different scenario starts its own sequence
    assert next_call_label("intake", tmp_path) == "call-01-intake"


def test_sequential_calls_never_collide(tmp_path: Path) -> None:
    # Each call reserves its number atomically, so back-to-back calls differ.
    labels = [next_call_label("scheduling", tmp_path) for _ in range(5)]
    assert labels == [
        "call-01-scheduling",
        "call-02-scheduling",
        "call-03-scheduling",
        "call-04-scheduling",
        "call-05-scheduling",
    ]
    assert len(set(labels)) == len(labels)


def test_zero_padded_two_digits_then_widens(tmp_path: Path) -> None:
    (tmp_path / "call-09-scheduling.txt").touch()
    assert next_call_label("scheduling", tmp_path) == "call-10-scheduling"
