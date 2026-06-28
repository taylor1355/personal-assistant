"""Pydantic models for proposals.

Schema and semantics are the source of truth in ``docs/PROPOSAL_FORMAT.md``.
``to_markdown`` (emit, used by the propose tool) and ``parse_proposal`` (read
back, used by the applier) are inverses; any schema change must keep them so.
"""
from __future__ import annotations

import re
from datetime import UTC, datetime
from enum import Enum
from typing import Annotated

import yaml
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)


# Note: ruff's UP042 wants StrEnum, but Mode.replace would shadow str.replace
# under StrEnum (mypy correctly catches this). Keeping (str, Enum) yields
# the same wire behaviour without the method-name collision.
class Action(str, Enum):  # noqa: UP042
    vault_edit = "vault_edit"
    vault_create = "vault_create"
    vault_delete = "vault_delete"
    vault_move = "vault_move"
    calendar_create = "calendar_create"
    calendar_update = "calendar_update"
    calendar_delete = "calendar_delete"
    email_draft = "email_draft"
    email_label = "email_label"
    email_archive = "email_archive"


class Status(str, Enum):  # noqa: UP042
    pending = "pending"
    approved = "approved"
    rejected = "rejected"
    applied = "applied"
    failed = "failed"


class Mode(str, Enum):  # noqa: UP042
    diff = "diff"
    # mypy thinks `replace` should be str.replace; the Enum metaclass
    # reassigns the name into an enum member at class-creation time.
    replace = "replace"  # type: ignore[assignment]


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
    # Second path for vault_move (the move/rename destination). For ``target``
    # as source, ``destination`` is where it lands. Unused by other actions.
    destination: str | None = None
    status: Status = Status.pending
    mode: Mode | None = None

    @field_validator("proposed_at")
    @classmethod
    def _must_be_utc(cls, v: datetime) -> datetime:
        if v.tzinfo is None or v.tzinfo.utcoffset(v) != UTC.utcoffset(v):
            raise ValueError("proposed_at must be UTC (tzinfo=timezone.utc)")
        return v

    @model_validator(mode="after")
    def _destination_required_for_move(self) -> ProposalFrontmatter:
        # A vault_move with no destination is incomplete; reject it at
        # construction so the agent gets feedback at propose time rather than
        # the proposal failing later in the applier.
        if self.action is Action.vault_move and not self.destination:
            raise ValueError("destination is required for vault_move")
        return self


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
        t = self.frontmatter.proposed_at.astimezone(UTC)
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
        if fm.destination is not None:
            lines.append(f"destination: {_yaml_quote(fm.destination)}")
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


class ProposalParseError(ValueError):
    """A proposal file is structurally malformed (bad frontmatter delimiters,
    missing required body section). Distinct from ``ValidationError``, which a
    well-formed-but-schema-invalid file raises. The applier catches both to
    mark a proposal ``failed`` rather than crash the sweep."""


_SECTION_KEYS = {
    "Intent": "intent",
    "Reasoning": "reasoning",
    "Change": "change",
    "Notes": "notes",
}
_HEADER_RE = re.compile(r"^##\s+(.+?)\s*$")


def parse_proposal(text: str, slug: str) -> Proposal:
    """Parse a proposal markdown file into a validated ``Proposal``.

    The inverse of ``Proposal.to_markdown``. The closed Pydantic schema
    re-validates on construction, so a tampered or drifted file raises here —
    this is the applier's authoritative re-check before it touches user state.
    ``slug`` comes from the filename (``YYYY-MM-DD-HHMM-<slug>.md``); it isn't
    stored in the file body.

    Raises ``ProposalParseError`` for structural damage and ``ValidationError``
    for schema violations (unknown frontmatter key, non-UTC timestamp, ...).
    """
    frontmatter_text, body_text = _split_frontmatter(text)
    raw = yaml.safe_load(frontmatter_text) or {}
    if not isinstance(raw, dict):
        raise ProposalParseError("frontmatter is not a key/value mapping")
    raw = _normalize_proposed_at(raw)

    sections = _split_body_sections(body_text)
    for required in ("intent", "reasoning", "change"):
        if required not in sections:
            raise ProposalParseError(
                f"missing required body section: ## {required.capitalize()}"
            )

    return Proposal(
        frontmatter=ProposalFrontmatter.model_validate(raw),
        body=ProposalBody(
            intent=sections["intent"],
            reasoning=sections["reasoning"],
            change=sections["change"],
            notes=sections.get("notes"),
        ),
        slug=slug,
    )


def _split_frontmatter(text: str) -> tuple[str, str]:
    """Split ``---``-delimited YAML frontmatter from the markdown body."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise ProposalParseError("file does not start with '---' frontmatter")
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            return "\n".join(lines[1:i]), "\n".join(lines[i + 1 :])
    raise ProposalParseError("unterminated frontmatter (no closing '---')")


def _normalize_proposed_at(raw: dict[str, object]) -> dict[str, object]:
    """YAML may parse the timestamp into a naive datetime; the schema requires
    UTC. Attach UTC when tz-naive; leave strings for Pydantic to coerce."""
    pa = raw.get("proposed_at")
    if isinstance(pa, datetime) and pa.tzinfo is None:
        return {**raw, "proposed_at": pa.replace(tzinfo=UTC)}
    return raw


def _split_body_sections(body: str) -> dict[str, str]:
    """Map ``## Section`` headers to their stripped content.

    Fence-aware (CommonMark): a ``## header`` inside a fenced code block — e.g.
    a markdown file body in a ``vault_create`` Change — is content, not a
    section break. Fence tracking records the fence character and run length so
    a shorter inner fence (``` inside a ```` block) does not close the outer
    one; a fence closes only on a same-char run at least as long as the opener.
    """
    sections: dict[str, str] = {}
    current: str | None = None
    buf: list[str] = []
    fence_char: str | None = None
    fence_len = 0
    for line in body.splitlines():
        opener = _fence_run(line)
        if opener is not None:
            char, length = opener
            if fence_char is None:
                fence_char, fence_len = char, length
            elif char == fence_char and length >= fence_len:
                fence_char, fence_len = None, 0
            buf.append(line)
            continue
        header = None if fence_char is not None else _HEADER_RE.match(line)
        if header and header.group(1) in _SECTION_KEYS:
            if current is not None:
                sections[current] = "\n".join(buf).strip()
            current = _SECTION_KEYS[header.group(1)]
            buf = []
            continue
        buf.append(line)
    if current is not None:
        sections[current] = "\n".join(buf).strip()
    return sections


def _fence_run(line: str) -> tuple[str, int] | None:
    """If ``line`` opens/closes a code fence, return (fence_char, run_length)."""
    stripped = line.lstrip()
    for char in ("`", "~"):
        if stripped.startswith(char * 3):
            return char, len(stripped) - len(stripped.lstrip(char))
    return None


def _yaml_quote(value: str) -> str:
    """Quote a YAML scalar when the content could otherwise be misparsed."""
    if value == "" or any(ch in value for ch in ':#\n"\'[]{}|>&*!%@`') or value.strip() != value:
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    return value
