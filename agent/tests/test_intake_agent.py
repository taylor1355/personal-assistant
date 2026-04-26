from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

from personal_assistant_agent.agents.intake_agent import (
    AGENT_NAME,
    IntakeItem,
    _classify,
    process_inbox,
)


def _fake_linear(create_output: str = "Created PA-7: Sample\nURL: https://...") -> MagicMock:
    """A LinearClient stand-in that records calls and returns a fixed create() output."""
    mock = MagicMock()
    mock.create.return_value = create_output
    return mock


# --- LLM-bypass path (items injected directly) ---


def test_linear_issue_branch_calls_create_with_expected_fields() -> None:
    linear = _fake_linear()
    item = IntakeItem(
        kind="linear_issue",
        summary="Research X",
        payload={
            "title": "Research X for the Y project",
            "description": "User asked while at lunch.",
            "type_label": "research",
            "strategic_labels": ["urgent"],
            "priority": 1,
            "state": "Todo",
        },
    )
    result = process_inbox(inbox_text="ignored", linear=linear, items=[item])

    assert result.linear_created == ["PA-7"]
    linear.create.assert_called_once_with(
        title="Research X for the Y project",
        description="User asked while at lunch.",
        priority=1,
        labels=["research", "urgent"],
        state="Todo",
    )


def test_linear_issue_falls_back_to_summary_for_title() -> None:
    """If the LLM omits 'title', we use 'summary' rather than fail."""
    linear = _fake_linear("Created PA-2: Whatever\nURL: ...")
    item = IntakeItem(
        kind="linear_issue",
        summary="A useful task to do",
        payload={"type_label": "life-task"},
    )
    process_inbox(inbox_text="x", linear=linear, items=[item])
    kwargs = linear.create.call_args.kwargs
    assert kwargs["title"] == "A useful task to do"
    assert kwargs["labels"] == ["life-task"]
    # description is optional; default is empty string per the wrapper.
    assert kwargs["description"] == ""


def test_linear_issue_with_no_type_label_passes_empty_labels() -> None:
    linear = _fake_linear()
    item = IntakeItem(kind="linear_issue", summary="Untyped", payload={})
    process_inbox(inbox_text="x", linear=linear, items=[item])
    kwargs = linear.create.call_args.kwargs
    assert kwargs["labels"] == []


def test_non_linear_kinds_are_deferred_not_attempted() -> None:
    linear = _fake_linear()
    items = [
        IntakeItem(kind="journal_entry", summary="Long day"),
        IntakeItem(kind="plan", summary="Beach trip", payload={"date": "2026-06-13"}),
        IntakeItem(kind="vault_todo", summary="Order more coffee filters"),
        IntakeItem(kind="calendar_item", summary="Dentist appointment"),
        IntakeItem(kind="question", summary="What was on my plate today?"),
        IntakeItem(kind="direct_command", summary="Remind me at 3pm"),
        IntakeItem(kind="noise", summary="lol"),
    ]
    result = process_inbox(inbox_text="x", linear=linear, items=items)
    assert linear.create.call_count == 0
    assert {d.kind for d in result.deferred} == {
        "journal_entry",
        "plan",
        "vault_todo",
        "calendar_item",
        "question",
        "direct_command",
        "noise",
    }
    assert result.linear_created == []


def test_create_failure_is_recorded_as_error_not_raised() -> None:
    linear = _fake_linear()
    linear.create.side_effect = RuntimeError("Linear API down")
    item = IntakeItem(
        kind="linear_issue",
        summary="Task that will fail to create",
        payload={"type_label": "life-task"},
    )
    result = process_inbox(inbox_text="x", linear=linear, items=[item])
    assert result.linear_created == []
    assert len(result.errors) == 1
    assert "Linear API down" in result.errors[0]


def test_unparseable_create_output_returns_no_identifier() -> None:
    """If the CLI's stdout doesn't include 'Created PA-N:', the create
    is recorded as having happened but we have no identifier to track."""
    linear = _fake_linear("(some unexpected output that doesn't include Created)")
    item = IntakeItem(kind="linear_issue", summary="X", payload={"type_label": "feature"})
    result = process_inbox(inbox_text="x", linear=linear, items=[item])
    # No identifier extracted; create still ran (no error), no Linear ID logged.
    assert result.linear_created == []
    assert result.errors == []


def test_mixed_batch_routes_each_item_independently() -> None:
    """Errors on one item don't stop processing of others."""
    linear = _fake_linear()
    # First create succeeds; second raises; third succeeds.
    linear.create.side_effect = [
        "Created PA-1: One\n",
        RuntimeError("rate limit"),
        "Created PA-3: Three\n",
    ]
    items = [
        IntakeItem(kind="linear_issue", summary="One", payload={"type_label": "feature"}),
        IntakeItem(kind="linear_issue", summary="Two", payload={"type_label": "feature"}),
        IntakeItem(kind="linear_issue", summary="Three", payload={"type_label": "feature"}),
    ]
    result = process_inbox(inbox_text="x", linear=linear, items=items)
    assert result.linear_created == ["PA-1", "PA-3"]
    assert len(result.errors) == 1
    assert "rate limit" in result.errors[0]
    assert linear.create.call_count == 3


# --- LLM path (mock Anthropic client) ---


class _FakeAnthropic:
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
                    name="report_items",
                    input=self._tool_input,
                )
            ]
        )


def test_classify_parses_tool_use_response() -> None:
    fake = _FakeAnthropic(
        tool_input={
            "items": [
                {
                    "kind": "linear_issue",
                    "summary": "Research X",
                    "title": "Research X for Y",
                    "type_label": "research",
                    "priority": 2,
                },
                {"kind": "noise", "summary": ""},
            ]
        }
    )
    items = _classify(inbox_text="some inbox text", client=fake, model="claude-opus-4-7")
    assert len(items) == 2
    assert items[0].kind == "linear_issue"
    assert items[0].summary == "Research X"
    assert items[0].payload == {
        "title": "Research X for Y",
        "type_label": "research",
        "priority": 2,
    }
    assert items[1].kind == "noise"


def test_classify_uses_forced_tool_choice() -> None:
    fake = _FakeAnthropic(tool_input={"items": []})
    _classify(inbox_text="x", client=fake, model="claude-opus-4-7")
    call = fake.messages.calls[0]
    assert call["tool_choice"] == {"type": "tool", "name": "report_items"}
    assert len(call["tools"]) == 1


def test_classify_returns_empty_when_no_tool_block() -> None:
    class _NoToolClient:
        class messages:
            @staticmethod
            def create(**_: Any) -> Any:
                return SimpleNamespace(content=[SimpleNamespace(type="text", text="hello")])

    items = _classify(inbox_text="x", client=_NoToolClient(), model="claude-opus-4-7")
    assert items == []


def test_end_to_end_classify_then_act() -> None:
    """Full path: LLM-classified items flow into LinearClient.create()."""
    fake = _FakeAnthropic(
        tool_input={
            "items": [
                {
                    "kind": "linear_issue",
                    "summary": "Buy groceries",
                    "title": "Buy groceries this week",
                    "type_label": "life-task",
                    "priority": 3,
                },
                {"kind": "journal_entry", "summary": "Tired today"},
            ]
        }
    )
    linear = _fake_linear("Created PA-5: Buy groceries this week\n")
    result = process_inbox(inbox_text="raw inbox", linear=linear, client=fake)
    assert result.linear_created == ["PA-5"]
    assert [d.kind for d in result.deferred] == ["journal_entry"]
    assert linear.create.call_count == 1


def test_AGENT_NAME_constant_exposed() -> None:
    """Other code references AGENT_NAME for proposal authoring (when wired)."""
    assert AGENT_NAME == "intake_agent"
