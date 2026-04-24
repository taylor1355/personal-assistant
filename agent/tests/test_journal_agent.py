from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any

import pytest

from personal_assistant_agent.agents.journal_agent import (
    AGENT_NAME,
    CompletionReport,
    _detect_completions,
    _strike_through,
    _unified_diff,
    detect_completed_todos,
)
from personal_assistant_agent.models import Action, Mode

TODOS = """\
### Health
- Gym 3x this week
- Drink more water
### Work
- Ship v0 scaffold
"""

JOURNAL = """\
Got my third gym session in today. Productive day.
"""

NOW = datetime(2026, 4, 24, 14, 30, 0, tzinfo=timezone.utc)


def test_strike_through_replaces_first_matching_bullet() -> None:
    out = _strike_through(TODOS, "Gym 3x this week")
    assert "- ~~Gym 3x this week~~ done" in out
    # Unrelated lines untouched.
    assert "- Drink more water" in out
    assert "- Ship v0 scaffold" in out


def test_strike_through_is_noop_when_line_absent() -> None:
    out = _strike_through(TODOS, "Learn French")
    assert out == TODOS


def test_strike_through_preserves_indentation() -> None:
    indented = "  - Gym 3x this week\n"
    out = _strike_through(indented, "Gym 3x this week")
    assert out == "  - ~~Gym 3x this week~~ done\n"


def test_detect_builds_proposal_with_expected_fields() -> None:
    report = CompletionReport(
        todo_line="Gym 3x this week",
        evidence="Got my third gym session in today.",
        slug="check-off-gym-todo",
    )
    proposals = detect_completed_todos(
        journal_text=JOURNAL,
        todos_text=TODOS,
        todos_file_path="02 - Todos/01 - Short Term Todos.md",
        now=NOW,
        completions=[report],
    )
    assert len(proposals) == 1
    p = proposals[0]
    assert p.frontmatter.agent == AGENT_NAME
    assert p.frontmatter.action == Action.vault_edit
    assert p.frontmatter.mode == Mode.diff
    assert p.frontmatter.target == "02 - Todos/01 - Short Term Todos.md"
    assert p.slug == "check-off-gym-todo"
    assert "```diff" in p.body.change
    assert "~~Gym 3x this week~~ done" in p.body.change
    assert "Got my third gym session in today." in p.body.reasoning


def test_detect_skips_phantom_completion() -> None:
    """LLM claims a todo is done but the literal line isn't present — skip."""
    report = CompletionReport(
        todo_line="Learn French",
        evidence="...",
        slug="phantom",
    )
    assert (
        detect_completed_todos(
            journal_text=JOURNAL,
            todos_text=TODOS,
            todos_file_path="t.md",
            now=NOW,
            completions=[report],
        )
        == []
    )


def test_detect_emits_one_proposal_per_completion() -> None:
    reports = [
        CompletionReport(
            todo_line="Gym 3x this week",
            evidence="third gym session",
            slug="check-off-gym",
        ),
        CompletionReport(
            todo_line="Drink more water",
            evidence="hit my water goal",
            slug="check-off-water",
        ),
    ]
    proposals = detect_completed_todos(
        journal_text=JOURNAL,
        todos_text=TODOS,
        todos_file_path="t.md",
        now=NOW,
        completions=reports,
    )
    assert [p.slug for p in proposals] == ["check-off-gym", "check-off-water"]


def test_unified_diff_has_path_prefixes() -> None:
    old = "a\nb\nc\n"
    new = "a\nb-edited\nc\n"
    diff = _unified_diff(old, new, "notes.md")
    assert diff.startswith("--- a/notes.md\n+++ b/notes.md\n")
    assert "-b" in diff
    assert "+b-edited" in diff


class _FakeMessages:
    """Minimal fake of anthropic.Anthropic().messages for _detect_completions."""

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


class _FakeAnthropic:
    def __init__(self, tool_input: dict[str, Any]) -> None:
        self.messages = _FakeMessages(tool_input)


def test_detect_completions_parses_tool_use_response() -> None:
    fake = _FakeAnthropic(
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
    out = _detect_completions(
        journal_text=JOURNAL,
        todos_text=TODOS,
        client=fake,  # type: ignore[arg-type]
        model="claude-opus-4-7",
    )
    assert out == [
        CompletionReport(
            todo_line="Gym 3x this week",
            evidence="third gym session today",
            slug="check-off-gym-todo",
        )
    ]
    # Verify the request shape looks right.
    call = fake.messages.calls[0]
    assert call["model"] == "claude-opus-4-7"
    assert call["tool_choice"] == {"type": "tool", "name": "report_completions"}
    assert len(call["tools"]) == 1
    assert call["tools"][0]["name"] == "report_completions"


def test_detect_completions_empty_when_no_tool_block() -> None:
    class _NoToolClient:
        class messages:
            @staticmethod
            def create(**_: Any) -> Any:
                return SimpleNamespace(content=[SimpleNamespace(type="text", text="no tools here")])

    out = _detect_completions(
        journal_text=JOURNAL,
        todos_text=TODOS,
        client=_NoToolClient(),  # type: ignore[arg-type]
        model="claude-opus-4-7",
    )
    assert out == []


def test_end_to_end_with_fake_client_builds_proposals() -> None:
    fake = _FakeAnthropic(
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
    proposals = detect_completed_todos(
        journal_text=JOURNAL,
        todos_text=TODOS,
        todos_file_path="02 - Todos/01 - Short Term Todos.md",
        now=NOW,
        client=fake,  # type: ignore[arg-type]
    )
    assert len(proposals) == 1
    assert "~~Gym 3x this week~~ done" in proposals[0].body.change


def test_no_api_key_raises_when_client_not_injected(monkeypatch: pytest.MonkeyPatch) -> None:
    """Sanity check: if neither client nor key is present, Anthropic SDK errors."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(Exception):
        _detect_completions(
            journal_text=JOURNAL,
            todos_text=TODOS,
            client=None,
            model="claude-opus-4-7",
        )
