"""Tests for the memory substrate's completion awareness (PA-102)."""
from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import pytest

from personal_assistant_agent.memory.completion import (
    Completion,
    CompletionSource,
    IssueState,
    StateType,
    diff_snapshots,
    is_terminal,
    load_snapshots,
    save_snapshots,
)


def _state(
    identifier: str,
    state: str,
    state_type: StateType = StateType.STARTED,
    title: str = "t",
) -> IssueState:
    return IssueState(
        identifier=identifier,
        title=title,
        state=state,
        state_type=state_type,
        updated_at="2026-10-08T00:00:00Z",
    )


def test_is_terminal_uses_state_type_not_name() -> None:
    # Renamed workflow states must not change terminality: only the type counts.
    assert is_terminal(StateType.COMPLETED)
    assert is_terminal(StateType.CANCELED)
    assert not is_terminal(StateType.STARTED)
    assert not is_terminal(StateType.UNSTARTED)
    assert not is_terminal(StateType.BACKLOG)
    assert not is_terminal(StateType.TRIAGE)
    assert not is_terminal(StateType.UNKNOWN)


def test_diff_reports_newly_completed() -> None:
    old = {"PA-1": _state("PA-1", "In Progress", StateType.STARTED)}
    new = {"PA-1": _state("PA-1", "Done", StateType.COMPLETED)}
    completions = diff_snapshots(old, new, project="Personal")
    assert len(completions) == 1
    assert completions[0].identifier == "PA-1"
    assert completions[0].state == "Done"
    assert completions[0].project == "Personal"
    assert completions[0].source == CompletionSource.LINEAR


def test_diff_does_not_rereport_already_done() -> None:
    # The anti-staleness core: a completion surfaces exactly once.
    done = _state("PA-1", "Done", StateType.COMPLETED)
    assert diff_snapshots({"PA-1": done}, {"PA-1": done}, project="Personal") == []


def test_diff_seeds_silently_on_first_run() -> None:
    # First run (no prior snapshot): seed silently, report nothing. Reporting
    # every already-Done issue would reproduce the stale-done bug.
    new = {
        "PA-9": _state("PA-9", "Done", StateType.COMPLETED),
        "PA-10": _state("PA-10", "Todo", StateType.UNSTARTED),
    }
    assert diff_snapshots({}, new, project="Personal") == []


def test_diff_ignores_non_terminal() -> None:
    old = {"PA-1": _state("PA-1", "Todo", StateType.UNSTARTED)}
    new = {
        "PA-1": _state("PA-1", "In Progress", StateType.STARTED),
        "PA-2": _state("PA-2", "Backlog", StateType.BACKLOG),
    }
    assert diff_snapshots(old, new, project="Personal") == []


def test_diff_unknown_state_type_never_terminal() -> None:
    old = {"PA-1": _state("PA-1", "Todo", StateType.UNSTARTED)}
    new = {"PA-1": _state("PA-1", "Done")}
    # state_type defaults to UNKNOWN: not terminal, so no completion. A
    # snapshot entry we can't classify must not be reported as done.
    assert diff_snapshots(old, new, project="Personal") == []


def test_snapshot_round_trip(tmp_path: Path) -> None:
    snaps = {
        "Personal": {
            "PA-1": _state("PA-1", "Todo", StateType.UNSTARTED, title="Buy milk"),
        }
    }
    save_snapshots(tmp_path, snaps)
    loaded = load_snapshots(tmp_path)
    loaded_state = loaded["Personal"]["PA-1"]
    assert loaded_state.title == "Buy milk"
    assert loaded_state.state == "Todo"
    assert loaded_state.state_type == StateType.UNSTARTED


def test_load_empty_when_missing(tmp_path: Path) -> None:
    assert load_snapshots(tmp_path) == {}


def test_load_corrupt_file_returns_empty(tmp_path: Path) -> None:
    # A half-written or corrupt snapshot file must not wedge the substrate:
    # the next refresh re-seeds silently.
    (tmp_path / "linear-snapshots.json").write_text("{not json", encoding="utf-8")
    assert load_snapshots(tmp_path) == {}


def test_load_legacy_snapshot_without_state_type_reseeds(tmp_path: Path) -> None:
    # Snapshots written before state_type existed can't distinguish terminal
    # from non-terminal by type; drop them so the next refresh seeds silently
    # instead of re-reporting every Done issue once.
    legacy = {"Personal": {"PA-1": {"identifier": "PA-1", "title": "t", "state": "Done"}}}
    (tmp_path / "linear-snapshots.json").write_text(json.dumps(legacy), encoding="utf-8")
    assert load_snapshots(tmp_path) == {}


def test_save_is_atomic_leaves_no_tempfiles(tmp_path: Path) -> None:
    snaps = {"Personal": {"PA-1": _state("PA-1", "Todo", StateType.UNSTARTED)}}
    save_snapshots(tmp_path, snaps)
    leftovers = [p for p in tmp_path.iterdir() if p.name.startswith(".snapshots-")]
    assert leftovers == []
    assert load_snapshots(tmp_path) == snaps


def test_completion_is_frozen() -> None:
    c = Completion(identifier="PA-1", title="t", project="Personal", state="Done")
    with pytest.raises(dataclasses.FrozenInstanceError):
        c.title = "changed"  # type: ignore[misc]


def test_issue_state_is_frozen() -> None:
    s = _state("PA-1", "Todo", StateType.UNSTARTED)
    with pytest.raises(dataclasses.FrozenInstanceError):
        s.title = "changed"  # type: ignore[misc]
