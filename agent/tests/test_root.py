from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from personal_assistant_agent.agents.root import (
    TODOS_FILE,
    extract_journal_section,
    handle_wake,
)

JOURNAL_TEMPLATE = """\
# 4-23
Yesterday's entry. Went for a run.

# 4-24
Got my third gym session in today. Productive.
Wrote a lot.

# 4-25
Tomorrow's placeholder. Should not appear.
"""

TODOS_TEXT = """\
### Health
- Gym 3x this week
- Drink more water
### Work
- Ship v0 scaffold
"""


def test_extract_section_returns_todays_lines() -> None:
    out = extract_journal_section(JOURNAL_TEMPLATE, date(2026, 4, 24))
    assert out == (
        "Got my third gym session in today. Productive.\n"
        "Wrote a lot."
    )


def test_extract_section_empty_when_absent() -> None:
    out = extract_journal_section(JOURNAL_TEMPLATE, date(2026, 4, 30))
    assert out == ""


def test_extract_section_matches_zero_padded_variants() -> None:
    text = "# 04-24\nfoo\n# 04-25\nbar\n"
    assert extract_journal_section(text, date(2026, 4, 24)) == "foo"


def test_extract_section_matches_unpadded_day() -> None:
    text = "# 4-4\nfoo\n# 4-5\nbar\n"
    assert extract_journal_section(text, date(2026, 4, 4)) == "foo"


def test_extract_section_ignores_nondate_headings() -> None:
    text = "# 4-23\npre\n# Random Heading\nnoise\n# 4-24\nhit\n# 4-25\nnext\n"
    out = extract_journal_section(text, date(2026, 4, 24))
    assert out == "hit"


def _make_vault(tmp_path: Path, journal: str = JOURNAL_TEMPLATE, todos: str = TODOS_TEXT) -> Path:
    (tmp_path / "01 - Journals").mkdir(parents=True, exist_ok=True)
    (tmp_path / "01 - Journals" / "2026 Entries.md").write_text(journal, encoding="utf-8")
    (tmp_path / "02 - Todos").mkdir(parents=True, exist_ok=True)
    (tmp_path / "02 - Todos" / "01 - Short Term Todos.md").write_text(todos, encoding="utf-8")
    return tmp_path


class _FakeAnthropic:
    """Returns a fixed tool_use block. Records calls for assertions."""

    def __init__(self, tool_input: dict[str, Any]) -> None:
        self.messages = _FakeMessages(tool_input)


class _FakeMessages:
    def __init__(self, tool_input: dict[str, Any]) -> None:
        self._tool_input = tool_input
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        return SimpleNamespace(
            content=[
                SimpleNamespace(
                    type="tool_use",
                    name="report_completions",
                    input=self._tool_input,
                )
            ]
        )


def test_handle_wake_emits_proposals(tmp_path: Path) -> None:
    vault = _make_vault(tmp_path / "vault")
    proposals_dir = tmp_path / "proposals"
    client = _FakeAnthropic(
        tool_input={
            "completions": [
                {
                    "todo_line": "Gym 3x this week",
                    "evidence": "third gym session today",
                    "slug": "check-off-gym-todo",
                }
            ]
        }
    )

    written = handle_wake(
        "test",
        vault_root=vault,
        proposals_dir=proposals_dir,
        now=datetime(2026, 4, 24, 14, 30, 0, tzinfo=UTC),
        timezone_name="UTC",
        client=client,  # type: ignore[arg-type]
    )

    assert len(written) == 1
    content = written[0].read_text(encoding="utf-8")
    assert "action: vault_edit" in content
    assert "mode: diff" in content
    assert "~~Gym 3x this week~~ done" in content
    # Journal section reached the LLM, not the full journal.
    call = client.messages.calls[0]
    user_content = call["messages"][0]["content"]
    assert "Got my third gym session in today" in user_content
    assert "Yesterday's entry" not in user_content
    assert "Tomorrow's placeholder" not in user_content


def test_handle_wake_no_entry_today_is_noop(tmp_path: Path) -> None:
    vault = _make_vault(tmp_path / "vault")
    proposals_dir = tmp_path / "proposals"

    # A client that would fail the test if called.
    class _ExplodingClient:
        class messages:
            @staticmethod
            def create(**_: Any) -> Any:
                raise AssertionError("LLM must not be called when today's section is empty")

    written = handle_wake(
        "test",
        vault_root=vault,
        proposals_dir=proposals_dir,
        now=datetime(2026, 5, 10, 12, 0, 0, tzinfo=UTC),  # no section for 5-10
        timezone_name="UTC",
        client=_ExplodingClient(),  # type: ignore[arg-type]
    )
    assert written == []


def test_handle_wake_passes_todos_path_through(tmp_path: Path) -> None:
    vault = _make_vault(tmp_path / "vault")
    proposals_dir = tmp_path / "proposals"
    client = _FakeAnthropic(
        tool_input={
            "completions": [
                {
                    "todo_line": "Ship v0 scaffold",
                    "evidence": "got the scaffold up",
                    "slug": "check-off-scaffold",
                }
            ]
        }
    )
    written = handle_wake(
        "test",
        vault_root=vault,
        proposals_dir=proposals_dir,
        now=datetime(2026, 4, 24, 14, 30, 0, tzinfo=UTC),
        timezone_name="UTC",
        client=client,  # type: ignore[arg-type]
    )
    assert len(written) == 1
    content = written[0].read_text(encoding="utf-8")
    assert f'target: "{TODOS_FILE}"' in content or f"target: {TODOS_FILE}" in content


def test_unknown_reason_is_noop(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """An unrecognized reason logs a warning and returns no proposals."""
    from personal_assistant_agent.agents.root import handle_wake

    written = handle_wake(
        "completely-made-up",
        vault_root=tmp_path,
        proposals_dir=tmp_path,
        now=datetime(2026, 4, 24, 14, 30, 0, tzinfo=UTC),
        timezone_name="UTC",
    )
    assert written == []
    out = capsys.readouterr().out
    assert "not recognized" in out


def test_inbox_reason_requires_linear_client(tmp_path: Path) -> None:
    from personal_assistant_agent.agents.root import handle_wake

    with pytest.raises(ValueError, match="LinearClient"):
        handle_wake(
            "inbox",
            vault_root=tmp_path,
            proposals_dir=tmp_path,
            now=datetime(2026, 4, 24, 14, 30, 0, tzinfo=UTC),
            timezone_name="UTC",
        )


def test_inbox_reason_with_empty_inbox_is_noop(tmp_path: Path) -> None:
    """No inbox file (or empty) → intake_agent runs, finds nothing,
    LinearClient never called. handle_wake returns no proposal paths."""
    from unittest.mock import MagicMock

    from personal_assistant_agent.agents.root import handle_wake

    linear = MagicMock()
    written = handle_wake(
        "inbox",
        vault_root=tmp_path,
        proposals_dir=tmp_path,
        now=datetime(2026, 4, 24, 14, 30, 0, tzinfo=UTC),
        timezone_name="UTC",
        linear=linear,
    )
    assert written == []
    linear.create.assert_not_called()


def test_inbox_reason_with_content_creates_linear_issues(tmp_path: Path) -> None:
    """End-to-end: inbox has content → intake_agent classifies → LinearClient.create
    called for each linear_issue item."""
    from unittest.mock import MagicMock

    from personal_assistant_agent.agents.root import handle_wake

    # Populate inbox.
    inbox_dir = tmp_path / "00 - Assistant"
    inbox_dir.mkdir(parents=True)
    (inbox_dir / "Inbox.md").write_text(
        "Buy birthday card for mom\n\nResearch async patterns in Rust",
        encoding="utf-8",
    )

    linear = MagicMock()
    linear.create.return_value = "Created PA-99: Buy birthday card for mom\nURL: ...\n"

    anthropic_client = _FakeAnthropic_Intake(
        tool_input={
            "items": [
                {
                    "kind": "linear_issue",
                    "summary": "Buy birthday card for mom",
                    "title": "Buy birthday card for mom",
                    "type_label": "life-task",
                    "priority": 3,
                },
                {
                    "kind": "linear_issue",
                    "summary": "Research async patterns in Rust",
                    "title": "Research async patterns in Rust",
                    "type_label": "research",
                    "priority": 3,
                },
            ]
        }
    )

    written = handle_wake(
        "inbox",
        vault_root=tmp_path,
        proposals_dir=tmp_path,
        now=datetime(2026, 4, 24, 14, 30, 0, tzinfo=UTC),
        timezone_name="UTC",
        client=anthropic_client,  # type: ignore[arg-type]
        linear=linear,
    )
    assert written == []  # intake doesn't emit proposal files yet
    assert linear.create.call_count == 2
    # Verify the LLM saw the actual inbox content.
    call_args = anthropic_client.messages.calls[0]
    user_content = call_args["messages"][0]["content"]
    assert "Buy birthday card for mom" in user_content
    assert "Research async patterns in Rust" in user_content


class _FakeAnthropic_Intake:
    """Like _FakeAnthropic but for the intake_agent's report_items tool."""

    def __init__(self, tool_input: dict[str, Any]) -> None:
        self.messages = _FakeMessages_Intake(tool_input)


class _FakeMessages_Intake:
    def __init__(self, tool_input: dict[str, Any]) -> None:
        self._tool_input = tool_input
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        return SimpleNamespace(
            content=[
                SimpleNamespace(
                    type="tool_use",
                    name="report_items",
                    input=self._tool_input,
                )
            ]
        )


def test_handle_wake_respects_timezone(tmp_path: Path) -> None:
    """A UTC timestamp near midnight can fall on different local dates."""
    # This journal has only 4-23 — if we pick up the entry, we resolved "today"
    # as 4-23 in local time. If we miss, we resolved as 4-24 in UTC.
    journal = "# 4-23\nLate-night win: finished the launch.\n"
    vault = _make_vault(tmp_path / "vault", journal=journal)
    proposals_dir = tmp_path / "proposals"
    client = _FakeAnthropic(tool_input={"completions": []})

    # 2026-04-24 02:00 UTC == 2026-04-23 22:00 America/New_York
    handle_wake(
        "test",
        vault_root=vault,
        proposals_dir=proposals_dir,
        now=datetime(2026, 4, 24, 2, 0, 0, tzinfo=UTC),
        timezone_name="America/New_York",
        client=client,  # type: ignore[arg-type]
    )
    # LLM was called, which proves today's section was found (non-empty).
    assert len(client.messages.calls) == 1
    assert "Late-night win" in client.messages.calls[0]["messages"][0]["content"]
