"""Pydantic models for proposals.

Schema and semantics are the source of truth in ``docs/PROPOSAL_FORMAT.md``.
Any change here requires a matching change on the Go executor side.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from enum import Enum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator


class Action(str, Enum):
    vault_edit = "vault_edit"
    vault_create = "vault_create"
    vault_delete = "vault_delete"
    calendar_create = "calendar_create"
    calendar_update = "calendar_update"
    calendar_delete = "calendar_delete"
    email_draft = "email_draft"
    email_label = "email_label"
    email_archive = "email_archive"


class Status(str, Enum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"
    applied = "applied"
    failed = "failed"


class Mode(str, Enum):
    diff = "diff"
    replace = "replace"


_SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")

Slug = Annotated[
    str,
    StringConstraints(min_length=1, max_length=40, pattern=_SLUG_RE.pattern),
]


class ProposalFrontmatter(BaseModel):
    """The YAML frontmatter at the top of a proposal file."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    proposed_at: datetime
    agent: str = Field(min_length=1)
    action: Action
    target: str = Field(min_length=1)
    status: Status = Status.pending
    mode: Mode | None = None

    @field_validator("proposed_at")
    @classmethod
    def _must_be_utc(cls, v: datetime) -> datetime:
        if v.tzinfo is None or v.tzinfo.utcoffset(v) != timezone.utc.utcoffset(v):
            raise ValueError("proposed_at must be UTC (tzinfo=timezone.utc)")
        return v


class ProposalBody(BaseModel):
    """The markdown body of a proposal, section-by-section."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    intent: str = Field(min_length=1)
    reasoning: str = Field(min_length=1)
    change: str = Field(min_length=1)
    notes: str | None = None


class Proposal(BaseModel):
    """A complete proposal — frontmatter + body + the slug that names the file."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    frontmatter: ProposalFrontmatter
    body: ProposalBody
    slug: Slug

    def filename(self) -> str:
        """``YYYY-MM-DD-HHMM-<slug>.md`` from the UTC proposed_at timestamp."""
        t = self.frontmatter.proposed_at.astimezone(timezone.utc)
        return f"{t.strftime('%Y-%m-%d-%H%M')}-{self.slug}.md"

    def to_markdown(self) -> str:
        """Render the proposal as a complete markdown file.

        The frontmatter is emitted with explicit field ordering to keep the
        output stable and human-readable. Enum values serialize as their
        string values.
        """
        fm = self.frontmatter
        lines: list[str] = ["---"]
        lines.append(f"proposed_at: {fm.proposed_at.strftime('%Y-%m-%dT%H:%M:%SZ')}")
        lines.append(f"agent: {fm.agent}")
        lines.append(f"action: {fm.action.value}")
        lines.append(f"target: {_yaml_quote(fm.target)}")
        lines.append(f"status: {fm.status.value}")
        if fm.mode is not None:
            lines.append(f"mode: {fm.mode.value}")
        lines.append("---")
        lines.append("")
        lines.append("## Intent")
        lines.append(self.body.intent.strip())
        lines.append("")
        lines.append("## Reasoning")
        lines.append(self.body.reasoning.strip())
        lines.append("")
        lines.append("## Change")
        lines.append(self.body.change.rstrip())
        if self.body.notes:
            lines.append("")
            lines.append("## Notes")
            lines.append(self.body.notes.strip())
        lines.append("")
        return "\n".join(lines)


def _yaml_quote(value: str) -> str:
    """Quote a YAML scalar when the content could otherwise be misparsed."""
    if value == "" or any(ch in value for ch in ':#\n"\'[]{}|>&*!%@`') or value.strip() != value:
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    return value
