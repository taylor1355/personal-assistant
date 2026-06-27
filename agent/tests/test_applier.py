from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from personal_assistant_agent.applier import sweep
from personal_assistant_agent.models import (
    Action,
    Mode,
    Proposal,
    ProposalBody,
    ProposalFrontmatter,
    Status,
)

NOW = datetime(2026, 6, 25, 9, 0, 0, tzinfo=UTC)


def _vault(tmp_path: Path) -> Path:
    root = tmp_path / "vault"
    root.mkdir()
    return root


def _write(
    proposals_dir: Path,
    *,
    action: Action,
    target: str,
    change: str,
    slug: str,
    status: Status = Status.approved,
    destination: str | None = None,
    mode: Mode | None = None,
) -> Path:
    proposal = Proposal(
        frontmatter=ProposalFrontmatter(
            proposed_at=datetime(2026, 6, 25, 8, 0, 0, tzinfo=UTC),
            agent="test",
            action=action,
            target=target,
            destination=destination,
            mode=mode,
            status=status,
        ),
        body=ProposalBody(intent="i", reasoning="r", change=change),
        slug=slug,
    )
    proposals_dir.mkdir(parents=True, exist_ok=True)
    path = proposals_dir / proposal.filename()
    path.write_text(proposal.to_markdown(), encoding="utf-8")
    return path


def _fenced(content: str) -> str:
    return f"```markdown\n{content}\n```"


# --- adapters: happy paths ---


def test_apply_vault_edit_replace_overwrites_and_archives(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    (vault / "02 - Todos").mkdir()
    target = vault / "02 - Todos" / "todos.md"
    target.write_text("- [ ] gym\n", encoding="utf-8")
    queue = vault / "00 - Proposals"
    _write(queue, action=Action.vault_edit, target="02 - Todos/todos.md",
           mode=Mode.replace, change=_fenced("- [x] gym"), slug="check-off-gym")

    outcomes = sweep(queue, vault, NOW)

    assert target.read_text(encoding="utf-8") == "- [x] gym"
    assert [o.status for o in outcomes] == [Status.applied]
    assert not list(queue.glob("*.md")), "applied proposal should leave the queue root"
    archived = list((queue / "Applied").rglob("*.md"))
    assert len(archived) == 1
    body = archived[0].read_text(encoding="utf-8")
    assert "status: applied" in body and "## Result" in body


def test_apply_vault_create_writes_new_file(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    queue = vault / "00 - Proposals"
    _write(queue, action=Action.vault_create, target="05 - Ideas/spark.md",
           change=_fenced("# Spark\n\nan idea"), slug="capture-spark")

    outcomes = sweep(queue, vault, NOW)

    assert (vault / "05 - Ideas" / "spark.md").read_text(encoding="utf-8") == "# Spark\n\nan idea"
    assert outcomes[0].status is Status.applied


def test_apply_vault_move_file(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    (vault / "05 - Ideas").mkdir()
    (vault / "05 - Ideas" / "draft.md").write_text("body", encoding="utf-8")
    queue = vault / "00 - Proposals"
    _write(queue, action=Action.vault_move, target="05 - Ideas/draft.md",
           destination="03 - Projects/draft.md", change="move it", slug="graduate-draft")

    outcomes = sweep(queue, vault, NOW)

    assert not (vault / "05 - Ideas" / "draft.md").exists()
    assert (vault / "03 - Projects" / "draft.md").read_text(encoding="utf-8") == "body"
    assert outcomes[0].status is Status.applied


def test_apply_vault_move_directory_moves_subtree(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    src = vault / "05 - Ideas" / "cluster"
    src.mkdir(parents=True)
    (src / "a.md").write_text("a", encoding="utf-8")
    (src / "b.md").write_text("b", encoding="utf-8")
    queue = vault / "00 - Proposals"
    _write(queue, action=Action.vault_move, target="05 - Ideas/cluster",
           destination="03 - Projects/cluster", change="reorg", slug="reorg-cluster")

    sweep(queue, vault, NOW)

    assert not src.exists()
    moved = vault / "03 - Projects" / "cluster"
    assert (moved / "a.md").read_text(encoding="utf-8") == "a"
    assert (moved / "b.md").read_text(encoding="utf-8") == "b"


# --- selection / no-op ---


def test_pending_proposal_is_left_untouched(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    (vault / "t.md").write_text("orig", encoding="utf-8")
    queue = vault / "00 - Proposals"
    path = _write(queue, action=Action.vault_edit, target="t.md", mode=Mode.replace,
                  change=_fenced("changed"), slug="x", status=Status.pending)

    outcomes = sweep(queue, vault, NOW)

    assert outcomes == []
    assert (vault / "t.md").read_text(encoding="utf-8") == "orig"
    assert path.exists() and "status: pending" in path.read_text(encoding="utf-8")


def test_applied_proposal_not_reprocessed_on_second_sweep(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    (vault / "t.md").write_text("orig", encoding="utf-8")
    queue = vault / "00 - Proposals"
    _write(queue, action=Action.vault_edit, target="t.md", mode=Mode.replace,
           change=_fenced("v1"), slug="x")

    assert len(sweep(queue, vault, NOW)) == 1
    assert sweep(queue, vault, NOW) == []  # archived; nothing left to do


# --- failure paths: marked failed, left in place, vault unharmed ---


def test_vault_edit_missing_target_fails_and_keeps_file(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    queue = vault / "00 - Proposals"
    path = _write(queue, action=Action.vault_edit, target="nope.md", mode=Mode.replace,
                  change=_fenced("x"), slug="edit-missing")

    outcomes = sweep(queue, vault, NOW)

    assert outcomes[0].status is Status.failed
    assert not (vault / "nope.md").exists()
    assert path.exists() and "status: failed" in path.read_text(encoding="utf-8")


def test_vault_edit_diff_mode_fails_with_pa25_hint(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    (vault / "t.md").write_text("orig", encoding="utf-8")
    queue = vault / "00 - Proposals"
    _write(queue, action=Action.vault_edit, target="t.md", mode=Mode.diff,
           change="```diff\n-orig\n+new\n```", slug="diff-edit")

    outcomes = sweep(queue, vault, NOW)

    assert outcomes[0].status is Status.failed
    assert "PA-25" in outcomes[0].detail
    assert (vault / "t.md").read_text(encoding="utf-8") == "orig"


def test_target_escaping_vault_is_refused(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    outside = tmp_path / "secret.md"
    outside.write_text("secret", encoding="utf-8")
    queue = vault / "00 - Proposals"
    _write(queue, action=Action.vault_edit, target="../secret.md", mode=Mode.replace,
           change=_fenced("pwned"), slug="escape")

    outcomes = sweep(queue, vault, NOW)

    assert outcomes[0].status is Status.failed
    assert outside.read_text(encoding="utf-8") == "secret"


def test_target_inside_proposal_queue_is_refused(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    queue = vault / "00 - Proposals"
    _write(queue, action=Action.vault_create, target="00 - Proposals/sneaky.md",
           change=_fenced("status: approved"), slug="queue-target")

    outcomes = sweep(queue, vault, NOW)

    assert outcomes[0].status is Status.failed
    assert not (queue / "sneaky.md").exists()


def test_move_refuses_to_overwrite_existing_destination(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    (vault / "a.md").write_text("a", encoding="utf-8")
    (vault / "b.md").write_text("b", encoding="utf-8")
    queue = vault / "00 - Proposals"
    _write(queue, action=Action.vault_move, target="a.md", destination="b.md",
           change="move", slug="clobber")

    outcomes = sweep(queue, vault, NOW)

    assert outcomes[0].status is Status.failed
    assert (vault / "a.md").read_text(encoding="utf-8") == "a"
    assert (vault / "b.md").read_text(encoding="utf-8") == "b"


def test_tampered_approved_proposal_fails_revalidation(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    (vault / "t.md").write_text("orig", encoding="utf-8")
    queue = vault / "00 - Proposals"
    path = _write(queue, action=Action.vault_edit, target="t.md", mode=Mode.replace,
                  change=_fenced("x"), slug="tampered")
    text = path.read_text(encoding="utf-8").replace(
        "status: approved\n", "status: approved\npriority: high\n"
    )
    path.write_text(text, encoding="utf-8")

    outcomes = sweep(queue, vault, NOW)

    assert outcomes[0].status is Status.failed
    assert (vault / "t.md").read_text(encoding="utf-8") == "orig"


# --- audit log ---


def test_audit_log_records_each_outcome(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    (vault / "t.md").write_text("orig", encoding="utf-8")
    queue = vault / "00 - Proposals"
    _write(queue, action=Action.vault_edit, target="t.md", mode=Mode.replace,
           change=_fenced("new"), slug="audited")
    audit = tmp_path / "audit.log"

    sweep(queue, vault, NOW, audit_log=audit)

    line = audit.read_text(encoding="utf-8").strip()
    assert "applied" in line and "vault_edit" in line and "audited" in line
