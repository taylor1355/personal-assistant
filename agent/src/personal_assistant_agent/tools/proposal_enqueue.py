"""Emit a proposal file to the proposals directory.

This is the agent's ONLY path to mutating user state. See
``docs/PROPOSAL_FORMAT.md`` for the full spec and invariants.
"""
from __future__ import annotations

import os
import tempfile
from datetime import datetime
from pathlib import Path

from personal_assistant_agent.models import (
    Action,
    Mode,
    Proposal,
    ProposalBody,
    ProposalFrontmatter,
)

DEFAULT_PROPOSALS_DIR = Path("/data/proposals")


class ProposalCollisionError(FileExistsError):
    """Raised when a proposal filename already exists in the target directory.

    Two proposals minted in the same UTC minute with the same slug collide;
    the caller should choose a distinguishing slug and retry.
    """


def build_proposal(
    *,
    action: str,
    target: str,
    intent: str,
    reasoning: str,
    change: str,
    slug: str,
    now: datetime,
    agent: str = "orchestrator",
    mode: str | None = None,
    destination: str | None = None,
    notes: str | None = None,
) -> Proposal:
    """Assemble a validated ``Proposal`` from primitive (string) tool inputs.

    The propose tool hands the LLM's raw arguments here. String ``action`` and
    ``mode`` are coerced to their enums — an unknown value raises ``ValueError``
    naming the offending input. The returned ``Proposal`` is fully validated by
    its closed Pydantic schema (UTC timestamp, kebab slug, no extra keys); the
    caller passes it to ``enqueue``. ``now`` is taken explicitly so callers
    control the timestamp (and tests stay deterministic). ``destination`` is the
    move target for ``vault_move``; omit it for every other action.
    """
    return Proposal(
        frontmatter=ProposalFrontmatter(
            proposed_at=now,
            agent=agent,
            action=Action(action),
            target=target,
            destination=destination,
            mode=Mode(mode) if mode is not None else None,
        ),
        body=ProposalBody(intent=intent, reasoning=reasoning, change=change, notes=notes),
        slug=slug,
    )


def enqueue(proposal: Proposal, proposals_dir: Path | None = None) -> Path:
    """Write a validated proposal file and return its path.

    The write is atomic on the same filesystem: the content is first written
    to a temp file, fsync'd, then renamed to the target. The executor's
    file-watcher must not observe a partial proposal.
    """
    target_dir = proposals_dir or _default_dir()
    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = target_dir / proposal.filename()
    if target_path.exists():
        raise ProposalCollisionError(str(target_path))

    content = proposal.to_markdown()

    fd, tmp_path_str = tempfile.mkstemp(
        prefix=".proposal-", suffix=".md.tmp", dir=str(target_dir)
    )
    tmp_path = Path(tmp_path_str)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, target_path)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise

    return target_path


def _default_dir() -> Path:
    env = os.environ.get("PROPOSALS_PATH")
    return Path(env) if env else DEFAULT_PROPOSALS_DIR
