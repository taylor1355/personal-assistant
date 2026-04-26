"""The journal_agent subagent.

Given today's journal entry text and the short-term todos file, detect
todos that appear completed and emit one proposal per completion. Each
proposal carries a ``mode: diff`` vault_edit that strikes the line through
and appends ``done``.

The LLM call is isolated in ``_detect_completions`` so tests can bypass it
by injecting completions directly. The outer ``detect_completed_todos``
builds the Proposal objects from the detection output.
"""
from __future__ import annotations

import difflib
import json
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any

from personal_assistant_agent.models import (
    Action,
    Mode,
    Proposal,
    ProposalBody,
    ProposalFrontmatter,
)

if TYPE_CHECKING:
    from anthropic import Anthropic

DEFAULT_MODEL = "claude-opus-4-7"
AGENT_NAME = "journal_agent"


@dataclass(frozen=True)
class CompletionReport:
    """A single completion the LLM identified."""

    todo_line: str      # the exact line in the todos file to strike through
    evidence: str       # a journal quote that supports the detection
    slug: str           # kebab-case slug for the proposal filename


def detect_completed_todos(
    *,
    journal_text: str,
    todos_text: str,
    todos_file_path: str,
    now: datetime,
    completions: list[CompletionReport] | None = None,
    client: Anthropic | None = None,
    model: str = DEFAULT_MODEL,
) -> list[Proposal]:
    """Return a list of proposals, one per detected completion.

    If ``completions`` is supplied, the LLM is not called — tests and
    callers with a pre-computed list can skip the network entirely.
    """
    if completions is None:
        completions = _detect_completions(
            journal_text=journal_text,
            todos_text=todos_text,
            client=client,
            model=model,
        )

    proposals: list[Proposal] = []
    for c in completions:
        new_todos = _strike_through(todos_text, c.todo_line)
        if new_todos == todos_text:
            # The LLM claimed a todo is done but its literal line isn't in
            # the file — skip rather than emit a no-op diff.
            continue
        diff = _unified_diff(todos_text, new_todos, todos_file_path)
        proposals.append(
            Proposal(
                frontmatter=ProposalFrontmatter(
                    proposed_at=now,
                    agent=AGENT_NAME,
                    action=Action.vault_edit,
                    target=todos_file_path,
                    mode=Mode.diff,
                ),
                body=ProposalBody(
                    intent=f"Mark '{c.todo_line}' as done — journal indicates it's complete.",
                    reasoning=f"Journal evidence: {c.evidence!r}",
                    change=f"```diff\n{diff}\n```",
                ),
                slug=c.slug,
            )
        )
    return proposals


def _strike_through(todos_text: str, todo_line: str) -> str:
    """Replace ``- <todo_line>`` with ``- ~~<todo_line>~~ done`` in-place.

    Only the first occurrence is replaced; if the line appears multiple
    times the caller should emit multiple detections with distinguishing
    evidence.
    """
    target_line = todo_line.strip()
    replacement_seen = False
    out: list[str] = []
    for line in todos_text.splitlines(keepends=True):
        stripped = line.rstrip("\r\n")
        if not replacement_seen and stripped.lstrip().startswith("- "):
            body = stripped.lstrip()[2:]
            if body.strip() == target_line:
                indent = stripped[: len(stripped) - len(stripped.lstrip())]
                newline = line[len(stripped):]
                out.append(f"{indent}- ~~{body}~~ done{newline}")
                replacement_seen = True
                continue
        out.append(line)
    return "".join(out)


def _unified_diff(old: str, new: str, path: str) -> str:
    """Return a unified diff string with ``a/`` + ``b/`` path prefixes."""
    diff_lines = difflib.unified_diff(
        old.splitlines(keepends=True),
        new.splitlines(keepends=True),
        fromfile=f"a/{path}",
        tofile=f"b/{path}",
        n=3,
    )
    return "".join(diff_lines).rstrip()


_COMPLETION_TOOL: dict[str, Any] = {
    "name": "report_completions",
    "description": (
        "Report todos that appear completed based on the journal entry. "
        "Only report items that the journal clearly indicates are done. "
        "Do not guess; it's fine to report an empty list."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "completions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "todo_line": {
                            "type": "string",
                            "description": (
                                "The exact text of the todo item from the todos "
                                "file, not including the leading '- '."
                            ),
                        },
                        "evidence": {
                            "type": "string",
                            "description": (
                                "A short quote from the journal that supports "
                                "the completion claim."
                            ),
                        },
                        "slug": {
                            "type": "string",
                            "description": (
                                "kebab-case slug, at most 40 characters, "
                                "summarizing the completion (e.g. "
                                "'check-off-gym-todo')."
                            ),
                        },
                    },
                    "required": ["todo_line", "evidence", "slug"],
                },
            },
        },
        "required": ["completions"],
    },
}

_SYSTEM_PROMPT = (
    "You are the journal_agent. You read today's journal entry and the "
    "user's short-term todo list, then identify which todo items appear "
    "to have been completed based on journal mentions. You do not mark "
    "anything as done yourself — you report detections via the "
    "report_completions tool, and a separate review step handles the "
    "actual edit.\n\n"
    "Be conservative. It is better to miss a completion than to "
    "falsely claim one. If the journal is ambiguous, skip it."
)

_USER_TEMPLATE = (
    "TODAY'S JOURNAL ENTRY:\n"
    "```\n"
    "{journal}\n"
    "```\n\n"
    "SHORT-TERM TODOS FILE:\n"
    "```\n"
    "{todos}\n"
    "```\n\n"
    "Call report_completions with the todos that appear done."
)


def _detect_completions(
    *,
    journal_text: str,
    todos_text: str,
    client: Anthropic | None,
    model: str,
) -> list[CompletionReport]:
    """Single-turn tool-use call against Anthropic."""
    if client is None:
        from anthropic import Anthropic

        client = Anthropic()

    # Anthropic SDK overloads expect TypedDicts for tools/tool_choice; we
    # construct dict literals that match the shape but mypy can't narrow.
    response = client.messages.create(  # type: ignore[call-overload]
        model=model,
        max_tokens=1024,
        system=_SYSTEM_PROMPT,
        tools=[_COMPLETION_TOOL],
        tool_choice={"type": "tool", "name": "report_completions"},
        messages=[
            {
                "role": "user",
                "content": _USER_TEMPLATE.format(
                    journal=journal_text, todos=todos_text
                ),
            }
        ],
    )

    for block in response.content:
        # Anthropic's SDK returns content blocks with .type == "tool_use"
        # for forced tool calls. Defensive attribute lookup handles both
        # pydantic-model responses and plain dicts in tests.
        block_type = getattr(block, "type", None) or (
            block.get("type") if isinstance(block, dict) else None
        )
        if block_type != "tool_use":
            continue
        raw = getattr(block, "input", None)
        if raw is None and isinstance(block, dict):
            raw = block.get("input")
        if isinstance(raw, str):
            raw = json.loads(raw)
        items = raw.get("completions", []) if isinstance(raw, dict) else []
        return [
            CompletionReport(
                todo_line=item["todo_line"],
                evidence=item["evidence"],
                slug=item["slug"],
            )
            for item in items
        ]
    return []
