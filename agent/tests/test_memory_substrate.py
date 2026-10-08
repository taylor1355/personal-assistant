"""Tests for the memory substrate's continuity log and orchestration (PA-102)."""
from __future__ import annotations

from pathlib import Path

from personal_assistant_agent.memory.completion import Completion, IssueState
from personal_assistant_agent.memory.continuity import (
    read_recent_entries,
    write_continuity_entry,
)
from personal_assistant_agent.memory.substrate import get_context, refresh


def _completion() -> Completion:
    return Completion(identifier="PA-1", title="Buy milk", state="Done")


def test_write_and_read_continuity(tmp_path: Path) -> None:
    mem = tmp_path / "Memory"
    write_continuity_entry(mem, completions=[_completion()], notes=["n1"])
    text = read_recent_entries(mem, days=1)
    assert "PA-1" in text
    assert "Buy milk" in text
    assert "n1" in text


def test_empty_refresh_still_writes_entry(tmp_path: Path) -> None:
    mem = tmp_path / "Memory"
    write_continuity_entry(mem)
    assert "No changes" in read_recent_entries(mem, days=1)


def test_appends_within_same_day(tmp_path: Path) -> None:
    mem = tmp_path / "Memory"
    write_continuity_entry(mem, notes=["first"])
    write_continuity_entry(mem, notes=["second"])
    text = read_recent_entries(mem, days=1)
    assert "first" in text and "second" in text


def test_read_empty_when_no_log(tmp_path: Path) -> None:
    assert read_recent_entries(tmp_path / "Memory", days=2) == ""


class _FakeLinear:
    """Minimal IssueStateSource: canned project states per refresh."""

    def __init__(self, states: list[IssueState]) -> None:
        self._states = states

    def project_states(self, name: str) -> list[IssueState]:
        assert name in ("Personal", "Dev")
        return self._states


def _vault(tmp_path: Path) -> Path:
    (tmp_path / "08 - Learning").mkdir()
    return tmp_path


def test_refresh_detects_completion_on_second_run(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    todo = IssueState(identifier="PA-1", title="t", state="Todo",
                      updated_at="2026-10-08T00:00:00Z")
    done = IssueState(identifier="PA-1", title="t", state="Done",
                      updated_at="2026-10-08T00:00:00Z")

    r1 = refresh(vault, _FakeLinear([todo]))
    assert r1.world_map_built
    assert r1.completions == []
    assert r1.projects_snapshotted == ("Personal", "Dev")

    r2 = refresh(vault, _FakeLinear([done]))
    # Reported once per snapshotted project (Personal + Dev share the fake).
    assert sorted(c.identifier for c in r2.completions) == ["PA-1", "PA-1"]

    # Third run: already reported, stays silent.
    r3 = refresh(vault, _FakeLinear([done]))
    assert r3.completions == []


def test_refresh_survives_project_failure(tmp_path: Path) -> None:
    class _Failing:
        def project_states(self, name: str) -> list[IssueState]:
            raise RuntimeError("boom")

    r = refresh(_vault(tmp_path), _Failing())
    assert r.world_map_built  # world-map still built
    assert r.projects_snapshotted == ()
    assert any("boom" in n for n in r.notes)


def test_get_context_reads_without_mutating(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    refresh(vault, _FakeLinear([]))
    ctx = get_context(vault, days=2)
    assert ctx.world_map is not None
    assert "08 - Learning" in ctx.world_map_json()
    # Continuity was written by the refresh ("No changes").
    assert "No changes" in ctx.continuity


def test_get_context_before_first_refresh(tmp_path: Path) -> None:
    ctx = get_context(tmp_path, days=2)
    assert ctx.world_map is None
    assert ctx.continuity == ""
    assert "not built yet" in ctx.world_map_json()
