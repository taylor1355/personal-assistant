"""Emit a proposal file to the proposals directory.

This is the agent's ONLY path to mutating user state. See
``docs/PROPOSAL_FORMAT.md`` for the full spec and invariants.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

from personal_assistant_agent.models import Proposal

DEFAULT_PROPOSALS_DIR = Path("/data/proposals")


class ProposalCollision(FileExistsError):
    """Raised when a proposal filename already exists in the target directory.

    Two proposals minted in the same UTC minute with the same slug collide;
    the caller should choose a distinguishing slug and retry.
    """


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
        raise ProposalCollision(str(target_path))

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
