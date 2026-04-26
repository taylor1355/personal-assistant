"""The intake_agent subagent.

Reads free-form text from the user's inbox (Obsidian or SMS), classifies
each item, and routes:

    linear_issue    → ``LinearClient.create(...)`` (auto-applied)
    journal_entry   → vault_edit proposal (deferred: executor not built)
    plan            → vault_create proposal (deferred)
    vault_todo      → vault_edit proposal (deferred)
    calendar_item   → calendar_create proposal (deferred)
    question        → response (deferred: SMS bridge not built)
    direct_command  → executed (deferred: routing TBD)
    noise           → no-op, archive in Raw/ (deferred)

Reads from: inbox text passed in by the caller.
Writes through: LinearClient (auto-applied) + proposal_enqueue (when
  vault-bound branches land).
Emits proposal action types: linear_create_issue (audit-only, deferred),
  vault_edit, vault_create.
Triggers it serves: ``inbox_edit``, ``sms_inbound``.
Escalates when: classification ambiguous AND user-facing decision
  required → SMS reply requesting clarification (deferred until SMS
  bridge lands).

v0 implementation handles the linear_issue branch only; other
classifications log and skip with a marker so the wake's session log
makes the deferral explicit.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

from personal_assistant_agent.tools.linear_cli import LinearClient

if TYPE_CHECKING:
    from anthropic import Anthropic

DEFAULT_MODEL = "claude-opus-4-7"
AGENT_NAME = "intake_agent"

ItemKind = Literal[
    "linear_issue",
    "journal_entry",
    "plan",
    "vault_todo",
    "calendar_item",
    "question",
    "direct_command",
    "noise",
]


@dataclass(frozen=True)
class IntakeItem:
    """A single classified chunk extracted from inbox content."""

    kind: ItemKind
    summary: str
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class IntakeResult:
    """Per-wake summary returned to the caller for session logging."""

    items: list[IntakeItem]
    linear_created: list[str]   # PA-N identifiers from successful creates
    deferred: list[IntakeItem]  # items whose handler isn't implemented yet
    errors: list[str]           # human-readable error lines


def process_inbox(
    *,
    inbox_text: str,
    linear: LinearClient,
    items: list[IntakeItem] | None = None,
    client: Anthropic | None = None,
    model: str = DEFAULT_MODEL,
) -> IntakeResult:
    """Classify ``inbox_text`` and act on each item.

    If ``items`` is supplied, the LLM is not called — tests inject the
    classified list directly to skip the network.
    """
    if items is None:
        items = _classify(inbox_text=inbox_text, client=client, model=model)

    linear_created: list[str] = []
    deferred: list[IntakeItem] = []
    errors: list[str] = []

    for item in items:
        if item.kind == "linear_issue":
            try:
                identifier = _create_linear_issue(item, linear)
                if identifier:
                    linear_created.append(identifier)
            except Exception as exc:  # narrow once LinearError surfaces real cases
                errors.append(f"linear_create failed for {item.summary!r}: {exc}")
        else:
            # All other branches not yet implemented; record so the session
            # log shows what was missed and the caller can prompt the user.
            deferred.append(item)

    return IntakeResult(
        items=items,
        linear_created=linear_created,
        deferred=deferred,
        errors=errors,
    )


def _create_linear_issue(item: IntakeItem, linear: LinearClient) -> str | None:
    """Create a Linear issue from a ``linear_issue`` item.

    Returns the new issue identifier (e.g. ``PA-12``) or None if the CLI
    output didn't contain one.
    """
    p = item.payload
    title = p.get("title") or item.summary
    description = p.get("description", "")
    type_label = p.get("type_label")
    strategic_labels = p.get("strategic_labels") or []
    priority = p.get("priority")  # 0-4 or None
    state = p.get("state") or "Triage"

    labels: list[str] = []
    if type_label:
        labels.append(type_label)
    labels.extend(strategic_labels)

    out = linear.create(
        title=title,
        description=description,
        priority=priority,
        labels=labels,
        state=state,
    )
    # The CLI prints "Created PA-NN: <title>"; pluck the identifier.
    for line in out.splitlines():
        if line.startswith("Created "):
            parts = line.split()
            if len(parts) >= 2 and parts[1].endswith(":"):
                return parts[1].rstrip(":")
            if len(parts) >= 2:
                return parts[1]
    return None


_LINEAR_TYPES = [
    "feature",
    "bug",
    "tech-debt",
    "investigation",
    "docs",
    "life-task",
    "research",
    "vault-organization",
    "reading",
    "health",
    "relationship",
]
_STRATEGIC = ["urgent", "quick-win", "keystone", "experiment", "ongoing"]


_INTAKE_TOOL: dict[str, Any] = {
    "name": "report_items",
    "description": (
        "Classify the user's inbox content into one or more items. "
        "Each chunk of text gets exactly one item; if a chunk is "
        "ambiguous or empty, classify as 'noise'. Be conservative — "
        "lean toward 'linear_issue' for anything that the user would "
        "want tracked, even loosely. Do NOT invent items the inbox "
        "doesn't support."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "kind": {
                            "type": "string",
                            "enum": [
                                "linear_issue",
                                "journal_entry",
                                "plan",
                                "vault_todo",
                                "calendar_item",
                                "question",
                                "direct_command",
                                "noise",
                            ],
                        },
                        "summary": {
                            "type": "string",
                            "description": "One-line summary of the item.",
                        },
                        "title": {
                            "type": "string",
                            "description": (
                                "For linear_issue: the issue title. "
                                "Concise, action-oriented when possible."
                            ),
                        },
                        "description": {
                            "type": "string",
                            "description": (
                                "For linear_issue: full body. Include the "
                                "original inbox text quoted, plus any "
                                "context the agent observed."
                            ),
                        },
                        "type_label": {
                            "type": "string",
                            "enum": _LINEAR_TYPES,
                            "description": "For linear_issue: the type label.",
                        },
                        "strategic_labels": {
                            "type": "array",
                            "items": {"type": "string", "enum": _STRATEGIC},
                            "description": "For linear_issue: optional strategic labels.",
                        },
                        "priority": {
                            "type": "integer",
                            "minimum": 0,
                            "maximum": 4,
                            "description": (
                                "For linear_issue: 0=None/Triage, 1=Urgent, "
                                "2=High, 3=Medium, 4=Low. Default unset = "
                                "Triage."
                            ),
                        },
                    },
                    "required": ["kind", "summary"],
                },
            },
        },
        "required": ["items"],
    },
}

_SYSTEM_PROMPT = (
    "You are intake_agent. The user dumps free-form thoughts into their "
    "inbox throughout the day — sometimes formatted, sometimes raw. "
    "Your job is to classify each chunk and extract enough structure for "
    "downstream subagents to act on it.\n\n"
    "Classify conservatively. Anything resembling a task, research "
    "question, idea-to-track, or commitment should be a 'linear_issue' "
    "so it's not lost. Only classify as 'noise' if the chunk has no "
    "clear intent (a stray newline, a dangling fragment, an emoji).\n\n"
    "For 'linear_issue', pick one of the registered type_label values "
    "and keep titles concise (under 80 chars). Default priority to 3 "
    "(Medium) unless the text indicates urgency."
)

_USER_TEMPLATE = (
    "INBOX CONTENT:\n"
    "```\n"
    "{inbox}\n"
    "```\n\n"
    "Call report_items with one entry per distinct chunk of intent in "
    "the inbox above."
)


def _classify(
    *,
    inbox_text: str,
    client: Anthropic | None,
    model: str,
) -> list[IntakeItem]:
    if client is None:
        from anthropic import Anthropic

        client = Anthropic()

    # Anthropic SDK overloads expect TypedDicts for tools/tool_choice; we
    # construct dict literals that match the shape but mypy can't narrow.
    response = client.messages.create(  # type: ignore[call-overload]
        model=model,
        max_tokens=2048,
        system=_SYSTEM_PROMPT,
        tools=[_INTAKE_TOOL],
        tool_choice={"type": "tool", "name": "report_items"},
        messages=[
            {"role": "user", "content": _USER_TEMPLATE.format(inbox=inbox_text)}
        ],
    )

    for block in response.content:
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
        items_raw = raw.get("items", []) if isinstance(raw, dict) else []
        return [
            IntakeItem(
                kind=item["kind"],
                summary=item["summary"],
                payload={
                    k: v
                    for k, v in item.items()
                    if k not in {"kind", "summary"}
                },
            )
            for item in items_raw
        ]
    return []
