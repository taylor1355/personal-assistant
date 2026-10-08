"""Tests for the memory substrate's completion awareness (PA-102)."""
from __future__ import annotations

from pathlib import Path

from personal_assistant_agent.memory.completion import (
    Completion,
    IssueState,
    diff_snapshots,
    is_terminal,
    load_snapshots,
    save_snapshots,
)


def _state(identifier: str, state: str, title: str = "t") -> IssueState:
    return IssueState(
        identifier=identifier, title=title, state=state,
        updated_at="2026-10-08T00:00:00Z",
    )


def test_is_terminal_covers_done_variants() -> None:
    assert is_terminal("Done")
    assert is_terminal("Cancelled")
    assert is_terminal("Canceled")
    assert not is_terminal("Todo")
    assert not is_terminal("In Progress")


def test_diff_reports_newly_completed() -> None:
    old = {"PA-1": _state("PA-1", "In Progress")}
    new = {"PA-1": _state("PA-1", "Done")}
    completions = diff_snapshots(old, new)
    assert len(completions) == 1
    assert completions[0].identifier == "PA-1"
    assert completions[0].state == "Done"
    assert completions[0].source == "linear"


def test_diff_does_not_rereport_already_done() -> None:
    # The anti-staleness core: a completion surfaces exactly once.
    done = _state("PA-1", "Done")
    assert diff_snapshots({"PA-1": done}, {"PA-1": done}) == []


def test_diff_reports_first_seen_done_once() -> None:
    completions = diff_snapshots({}, {"PA-9": _state("PA-9", "Done")})
    assert [c.identifier for c in completions] == ["PA-9"]
    # Second diff against the persisted snapshot: silent.
    snap = {"PA-9": _state("PA-9", "Done")}
    assert diff_snapshots(snap, snap) == []


def test_diff_ignores_non_terminal() -> None:
    old = {"PA-1": _state("PA-1", "Todo")}
    new = {"PA-1": _state("PA-1", "In Progress"), "PA-2": _state("PA-2", "Backlog")}
    assert diff_snapshots(old, new) == []


def test_snapshot_round_trip(tmp_path: Path) -> None:
    snaps = {"Personal": {"PA-1": _state("PA-1", "Todo", title="Buy milk")}}
    save_snapshots(tmp_path, snaps)
    loaded = load_snapshots(tmp_path)
    assert loaded["Personal"]["PA-1"].title == "Buy milk"
    assert loaded["Personal"]["PA-1"].state == "Todo"


def test_load_empty_when_missing(tmp_path: Path) -> None:
    assert load_snapshots(tmp_path) == {}


def test_completion_is_frozen() -> None:
    c = Completion(identifier="PA-1", title="t", state="Done")
    assert c.source == "linear"
