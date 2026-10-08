"""Tests for the memory substrate's continuity log and orchestration (PA-102)."""
from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from personal_assistant_agent.memory.completion import (
    Completion,
    CompletionSource,
    IssueState,
    StateType,
)
from personal_assistant_agent.memory.continuity import (
    read_recent_entries,
    write_continuity_entry,
)
from personal_assistant_agent.memory.substrate import get_context, refresh
from personal_assistant_agent.tools.linear_cli import LinearError

PROJECTS = ("Personal", "Dev")


def _completion(
    identifier: str = "PA-1",
    title: str = "Buy milk",
    project: str = "Personal",
) -> Completion:
    return Completion(
        identifier=identifier,
        title=title,
        project=project,
        state="Done",
        source=CompletionSource.LINEAR,
    )


def test_write_and_read_continuity(tmp_path: Path) -> None:
    mem = tmp_path / "Memory"
    write_continuity_entry(mem, completions=[_completion()], notes=["n1"])
    text = read_recent_entries(mem, days=1)
    assert "PA-1" in text
    assert "Buy milk" in text
    assert "[Personal]" in text
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


def test_continuity_buckets_by_local_day(tmp_path: Path) -> None:
    # 23:30 America/New_York is 03:30 UTC the next day — a UTC bucket would
    # file this under Oct 9, putting an evening completion in "tomorrow".
    mem = tmp_path / "Memory"
    evening = datetime(2026, 10, 8, 23, 30, tzinfo=ZoneInfo("America/New_York"))
    write_continuity_entry(mem, now=evening, notes=["late"])
    assert (mem / "continuity" / "2026-10-08.md").is_file()
    assert not (mem / "continuity" / "2026-10-09.md").exists()


def test_read_recent_entries_uses_injected_now(tmp_path: Path) -> None:
    mem = tmp_path / "Memory"
    write_continuity_entry(mem, day=date(2026, 10, 8), notes=["x"])
    now = datetime(2026, 10, 10, 12, tzinfo=UTC)
    assert read_recent_entries(mem, days=1, now=now) == ""
    assert "x" in read_recent_entries(mem, days=3, now=now)


def test_read_recent_entries_filters_by_project(tmp_path: Path) -> None:
    mem = tmp_path / "Memory"
    write_continuity_entry(
        mem,
        completions=[
            _completion("PA-1", "dev thing", project="Dev"),
            _completion("PA-2", "life thing", project="Personal"),
        ],
    )
    personal = read_recent_entries(mem, days=1, project="Personal")
    assert "PA-2" in personal
    assert "PA-1" not in personal
    dev = read_recent_entries(mem, days=1, project="Dev")
    assert "PA-1" in dev
    assert "PA-2" not in dev
    both = read_recent_entries(mem, days=1)
    assert "PA-1" in both and "PA-2" in both


class _FakeLinear:
    """Minimal IssueStateSource: canned project states per refresh."""

    def __init__(self, states: list[IssueState]) -> None:
        self._states = states

    def project_states(self, name: str) -> list[IssueState]:
        assert name in PROJECTS
        return self._states


def _vault(tmp_path: Path) -> Path:
    (tmp_path / "08 - Learning").mkdir()
    return tmp_path


def _issue(identifier: str, state: str, state_type: StateType) -> IssueState:
    return IssueState(
        identifier=identifier,
        title="t",
        state=state,
        state_type=state_type,
        updated_at="2026-10-08T00:00:00Z",
    )


def test_refresh_first_run_with_done_issues_reports_nothing(tmp_path: Path) -> None:
    # The first-run seeding rule at the refresh level: a project whose issues
    # are already Done must not surface them as completions.
    vault = _vault(tmp_path)
    done = _issue("PA-9", "Done", StateType.COMPLETED)
    r = refresh(vault, _FakeLinear([done]), projects=PROJECTS)
    assert r.world_map_built
    assert r.completions == []
    assert r.projects_snapshotted == PROJECTS


def test_refresh_detects_completion_on_second_run(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    todo = _issue("PA-1", "Todo", StateType.UNSTARTED)
    done = _issue("PA-1", "Done", StateType.COMPLETED)

    r1 = refresh(vault, _FakeLinear([todo]), projects=PROJECTS)
    assert r1.world_map_built
    assert r1.completions == []
    assert r1.projects_snapshotted == PROJECTS

    r2 = refresh(vault, _FakeLinear([done]), projects=PROJECTS)
    # Reported once per snapshotted project (Personal + Dev share the fake).
    assert sorted(c.identifier for c in r2.completions) == ["PA-1", "PA-1"]
    assert {c.project for c in r2.completions} == {"Personal", "Dev"}

    # Third run: already reported, stays silent.
    r3 = refresh(vault, _FakeLinear([done]), projects=PROJECTS)
    assert r3.completions == []


def test_refresh_survives_project_failure(tmp_path: Path) -> None:
    class _Failing:
        def project_states(self, name: str) -> list[IssueState]:
            raise LinearError(-1, "", "boom", ["project-states", name])

    r = refresh(_vault(tmp_path), _Failing(), projects=PROJECTS)
    assert r.world_map_built  # world-map still built
    assert r.projects_snapshotted == ()
    assert any("boom" in n for n in r.notes)


def test_get_context_reads_without_mutating(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    refresh(vault, _FakeLinear([]), projects=PROJECTS)
    ctx = get_context(vault, days=2)
    assert ctx.world_map is not None
    assert "08 - Learning" in ctx.world_map_json()
    # Continuity was written by the refresh ("No changes").
    assert "No changes" in ctx.continuity


def test_get_context_filters_continuity_by_project(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    states = [
        _issue("PA-1", "Todo", StateType.UNSTARTED),
    ]
    refresh(vault, _FakeLinear(states), projects=PROJECTS)
    # Complete PA-1, then read per project.
    refresh(vault, _FakeLinear([_issue("PA-1", "Done", StateType.COMPLETED)]), projects=PROJECTS)
    personal = get_context(vault, project="Personal")
    assert "PA-1" in personal.continuity
    # A project with no completions sees no completion lines.
    other = get_context(vault, project="Nonexistent")
    assert "PA-1" not in other.continuity


def test_get_context_before_first_refresh(tmp_path: Path) -> None:
    ctx = get_context(tmp_path, days=2)
    assert ctx.world_map is None
    assert ctx.continuity == ""
    assert "not built yet" in ctx.world_map_json()
