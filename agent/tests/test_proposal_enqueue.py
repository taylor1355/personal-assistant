from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from personal_assistant_agent.models import (
    Action,
    Mode,
    Proposal,
    ProposalBody,
    ProposalFrontmatter,
    ProposalParseError,
    Status,
    parse_proposal,
)
from personal_assistant_agent.tools.proposal_enqueue import (
    ProposalCollisionError,
    build_proposal,
    enqueue,
)

_UTC_NOW = datetime(2026, 4, 24, 14, 30, 0, tzinfo=UTC)


def _build(**overrides: object) -> Proposal:
    """build_proposal with valid defaults; override one field per test."""
    kwargs: dict[str, object] = dict(
        action="vault_edit",
        target="02 - Todos/01 - Short Term Todos.md",
        intent="Check off 'Gym 3x this week'.",
        reasoning="Journal: 'Got my third gym session in.'",
        change="```diff\n-- Gym 3x this week\n++ done\n```",
        slug="check-off-gym-todo",
        now=_UTC_NOW,
        mode="diff",
    )
    kwargs.update(overrides)
    return build_proposal(**kwargs)  # type: ignore[arg-type]


def _sample(
    *,
    at: datetime | None = None,
    slug: str = "check-off-gym-todo",
    action: Action = Action.vault_edit,
    mode: Mode | None = Mode.diff,
    notes: str | None = None,
) -> Proposal:
    return Proposal(
        frontmatter=ProposalFrontmatter(
            proposed_at=at or datetime(2026, 4, 24, 14, 30, 0, tzinfo=UTC),
            agent="journal_agent",
            action=action,
            target="02 - Todos/01 - Short Term Todos.md",
            mode=mode,
        ),
        body=ProposalBody(
            intent="Check off 'Gym 3x this week' — journal says it's done.",
            reasoning="2026-04-24 journal entry: 'Got my third gym session in today.'",
            change="```diff\n-- Gym 3x this week\n++ ~~Gym 3x this week~~ done\n```",
            notes=notes,
        ),
        slug=slug,
    )


def test_filename_is_utc_minute_plus_slug() -> None:
    p = _sample()
    assert p.filename() == "2026-04-24-1430-check-off-gym-todo.md"


def test_to_markdown_has_required_sections() -> None:
    md = _sample().to_markdown()
    assert md.startswith("---\n")
    assert "\nagent: journal_agent\n" in md
    assert "\naction: vault_edit\n" in md
    assert "\nstatus: pending\n" in md
    assert "\nmode: diff\n" in md
    assert "## Intent\n" in md
    assert "## Reasoning\n" in md
    assert "## Change\n" in md
    assert "## Notes" not in md


def test_notes_section_appears_when_set() -> None:
    md = _sample(notes="Follow up if two more mentions land this week.").to_markdown()
    assert "## Notes\n" in md


def test_target_with_colon_is_yaml_quoted() -> None:
    p = Proposal(
        frontmatter=ProposalFrontmatter(
            proposed_at=datetime(2026, 4, 24, 14, 30, 0, tzinfo=UTC),
            agent="journal_agent",
            action=Action.vault_edit,
            target="path: with a colon.md",
        ),
        body=ProposalBody(
            intent="x", reasoning="y", change="z"
        ),
        slug="colon-target",
    )
    assert '\ntarget: "path: with a colon.md"\n' in p.to_markdown()


def test_non_utc_timestamp_rejected() -> None:
    with pytest.raises(ValidationError):
        ProposalFrontmatter(
            proposed_at=datetime(2026, 4, 24, 14, 30, 0),  # naive
            agent="journal_agent",
            action=Action.vault_edit,
            target="t.md",
        )


@pytest.mark.parametrize("slug", ["Has-Upper", "has_underscore", "trailing-", "-leading", ""])
def test_invalid_slug_rejected(slug: str) -> None:
    with pytest.raises(ValidationError):
        Proposal(
            frontmatter=ProposalFrontmatter(
                proposed_at=datetime(2026, 4, 24, 14, 30, 0, tzinfo=UTC),
                agent="journal_agent",
                action=Action.vault_edit,
                target="t.md",
            ),
            body=ProposalBody(intent="x", reasoning="y", change="z"),
            slug=slug,
        )


def test_slug_over_40_chars_rejected() -> None:
    with pytest.raises(ValidationError):
        Proposal(
            frontmatter=ProposalFrontmatter(
                proposed_at=datetime(2026, 4, 24, 14, 30, 0, tzinfo=UTC),
                agent="journal_agent",
                action=Action.vault_edit,
                target="t.md",
            ),
            body=ProposalBody(intent="x", reasoning="y", change="z"),
            slug="a" * 41,
        )


def test_unknown_action_rejected() -> None:
    with pytest.raises(ValidationError):
        ProposalFrontmatter(
            proposed_at=datetime(2026, 4, 24, 14, 30, 0, tzinfo=UTC),
            agent="journal_agent",
            action="teleport_into_vault",  # type: ignore[arg-type]
            target="t.md",
        )


def test_extra_frontmatter_key_rejected() -> None:
    """Schema must be closed: unknown keys break the executor contract."""
    with pytest.raises(ValidationError):
        ProposalFrontmatter(
            proposed_at=datetime(2026, 4, 24, 14, 30, 0, tzinfo=UTC),
            agent="journal_agent",
            action=Action.vault_edit,
            target="t.md",
            priority="high",  # type: ignore[call-arg]
        )


def test_status_defaults_to_pending() -> None:
    p = _sample()
    assert p.frontmatter.status == Status.pending


def test_enqueue_writes_file(tmp_path: Path) -> None:
    p = _sample()
    out = enqueue(p, proposals_dir=tmp_path)
    assert out.name == "2026-04-24-1430-check-off-gym-todo.md"
    assert out.read_text(encoding="utf-8") == p.to_markdown()


def test_enqueue_is_atomic_no_partial_tmp_left(tmp_path: Path) -> None:
    """After a successful write, no .tmp turds remain in the proposals dir."""
    enqueue(_sample(), proposals_dir=tmp_path)
    leftovers = [p.name for p in tmp_path.iterdir() if p.name.startswith(".proposal-")]
    assert leftovers == []


def test_enqueue_collision_raises(tmp_path: Path) -> None:
    enqueue(_sample(), proposals_dir=tmp_path)
    with pytest.raises(ProposalCollisionError):
        enqueue(_sample(), proposals_dir=tmp_path)


def test_enqueue_uses_env_default(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PROPOSALS_PATH", str(tmp_path))
    out = enqueue(_sample())
    assert out.parent == tmp_path


# --- build_proposal: primitive tool inputs -> validated Proposal ---


def test_build_proposal_coerces_string_action_and_mode() -> None:
    p = _build(action="vault_create", mode="replace")
    assert p.frontmatter.action is Action.vault_create
    assert p.frontmatter.mode is Mode.replace


def test_build_proposal_omits_mode_when_none() -> None:
    assert _build(mode=None).frontmatter.mode is None


def test_build_proposal_defaults_agent_to_orchestrator() -> None:
    assert _build().frontmatter.agent == "orchestrator"


def test_build_proposal_uses_provided_now() -> None:
    when = datetime(2026, 1, 2, 3, 4, 0, tzinfo=UTC)
    p = _build(now=when)
    assert p.frontmatter.proposed_at == when
    assert p.filename() == "2026-01-02-0304-check-off-gym-todo.md"


def test_build_proposal_unknown_action_raises_valueerror() -> None:
    # ValueError (not ValidationError) is the contract the propose tool's
    # except clause relies on to give the LLM the valid-action list.
    with pytest.raises(ValueError):
        _build(action="teleport_into_vault")


def test_build_proposal_invalid_slug_raises_validationerror() -> None:
    # The closed schema must still bite when reached through the helper.
    with pytest.raises(ValidationError):
        _build(slug="Has_Underscore")


def test_build_proposal_then_enqueue_roundtrip(tmp_path: Path) -> None:
    p = _build()
    out = enqueue(p, proposals_dir=tmp_path)
    assert out.name == "2026-04-24-1430-check-off-gym-todo.md"
    assert out.read_text(encoding="utf-8") == p.to_markdown()


# --- parse_proposal: read a proposal file back into a validated Proposal ---


@pytest.mark.parametrize(
    "proposal",
    [
        _sample(),
        _sample(notes="Follow up if two more mentions land this week."),
        _sample(action=Action.vault_delete, mode=None),
    ],
)
def test_parse_proposal_roundtrips(proposal: Proposal) -> None:
    # to_markdown -> parse_proposal must reproduce the original exactly; this
    # is the encode/decode contract the applier relies on.
    assert parse_proposal(proposal.to_markdown(), proposal.slug) == proposal


def test_parse_proposal_preserves_headers_inside_fenced_change() -> None:
    # A vault_create Change carries a full note body — its own '## headers'
    # are content, not section breaks. The fence-aware splitter must not cut on
    # them, or the parsed change is truncated.
    change = "```markdown\n# Note\n\n## Section A\nalpha\n\n## Section B\nbeta\n```"
    p = Proposal(
        frontmatter=ProposalFrontmatter(
            proposed_at=datetime(2026, 4, 24, 14, 30, tzinfo=UTC),
            agent="intake_agent",
            action=Action.vault_create,
            target="05 - Ideas/new-note.md",
            mode=Mode.replace,
        ),
        body=ProposalBody(intent="Create a note.", reasoning="User asked.", change=change),
        slug="create-new-note",
    )
    parsed = parse_proposal(p.to_markdown(), p.slug)
    assert "## Section A" in parsed.body.change
    assert "## Section B" in parsed.body.change
    assert parsed == p


def test_parse_proposal_reads_approved_status() -> None:
    # The applier parses files the user has flipped to approved.
    md = _sample().to_markdown().replace("status: pending", "status: approved")
    assert parse_proposal(md, "check-off-gym-todo").frontmatter.status is Status.approved


def test_parse_proposal_rejects_missing_frontmatter() -> None:
    with pytest.raises(ProposalParseError):
        parse_proposal("## Intent\nx\n\n## Reasoning\ny\n\n## Change\nz\n", "no-fm")


def test_parse_proposal_rejects_unterminated_frontmatter() -> None:
    with pytest.raises(ProposalParseError):
        parse_proposal("---\naction: vault_edit\n", "unterminated")


def test_parse_proposal_rejects_missing_change_section() -> None:
    md = _sample().to_markdown().split("## Change")[0]
    with pytest.raises(ProposalParseError):
        parse_proposal(md, "check-off-gym-todo")


def test_destination_emitted_and_roundtrips_for_move() -> None:
    p = Proposal(
        frontmatter=ProposalFrontmatter(
            proposed_at=datetime(2026, 4, 24, 14, 30, tzinfo=UTC),
            agent="intake_agent",
            action=Action.vault_move,
            target="05 - Ideas/draft.md",
            destination="03 - Personal Projects/draft.md",
        ),
        body=ProposalBody(
            intent="Move the draft into projects.",
            reasoning="It graduated from idea to active project.",
            change="move 05 - Ideas/draft.md -> 03 - Personal Projects/draft.md",
        ),
        slug="move-draft-to-projects",
    )
    md = p.to_markdown()
    assert "\ndestination: 03 - Personal Projects/draft.md\n" in md
    assert parse_proposal(md, p.slug) == p


def test_destination_absent_from_markdown_when_none() -> None:
    assert "\ndestination:" not in _sample().to_markdown()


def test_vault_move_without_destination_rejected() -> None:
    # The model validator must reject an incomplete move at construction.
    with pytest.raises(ValidationError):
        ProposalFrontmatter(
            proposed_at=datetime(2026, 4, 24, 14, 30, tzinfo=UTC),
            agent="intake_agent",
            action=Action.vault_move,
            target="05 - Ideas/draft.md",
        )


def test_parse_proposal_preserves_nested_fences_in_change() -> None:
    # A note body (vault_create) can hold its own ``` code block; wrapping it in
    # a longer ```` fence must round-trip — the inner block and any '## header'
    # inside it stay content, not section breaks.
    change = "````markdown\n# Title\n\n## Heading\n\n```python\nx = 1\n```\n````"
    p = Proposal(
        frontmatter=ProposalFrontmatter(
            proposed_at=datetime(2026, 4, 24, 14, 30, tzinfo=UTC),
            agent="intake_agent",
            action=Action.vault_create,
            target="05 - Ideas/note.md",
            mode=Mode.replace,
        ),
        body=ProposalBody(intent="Create note.", reasoning="User asked.", change=change),
        slug="note-with-code",
    )
    parsed = parse_proposal(p.to_markdown(), p.slug)
    assert "## Heading" in parsed.body.change
    assert "```python" in parsed.body.change
    assert parsed == p


def test_build_proposal_passes_destination() -> None:
    p = _build(action="vault_move", destination="03 - Personal Projects/x.md", mode=None)
    assert p.frontmatter.destination == "03 - Personal Projects/x.md"


def test_parse_proposal_revalidates_closed_schema() -> None:
    # A drifted/tampered file with an unknown frontmatter key must not parse —
    # the applier's authoritative re-check, not just the emit-time check.
    md = _sample().to_markdown().replace("status: pending\n", "status: pending\npriority: high\n")
    with pytest.raises(ValidationError):
        parse_proposal(md, "check-off-gym-todo")
