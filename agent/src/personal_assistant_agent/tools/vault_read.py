"""Read from the agent's vault copy.

The agent container mounts the vault copy at ``/data/vault`` (or whatever
``VAULT_ROOT`` points at during local dev). Writes are never performed here
— those flow through the proposal queue.
"""
from __future__ import annotations

import os
from pathlib import Path

DEFAULT_VAULT_ROOT = Path("/data/vault")


class VaultPathError(ValueError):
    """Raised when a requested path would escape the vault root."""


def read_vault_file(relative_path: str, vault_root: Path | None = None) -> str:
    """Read a UTF-8 file under the vault root.

    ``relative_path`` is interpreted relative to the vault root. Absolute
    paths, ``..`` traversal, and symlinks pointing outside the vault are
    rejected — the tool is read-only, but a traversal bug would still leak
    host filesystem content into prompts.
    """
    root = (vault_root or _default_root()).resolve()
    rel = Path(relative_path)
    if rel.is_absolute():
        raise VaultPathError(f"relative_path must be relative: {relative_path!r}")

    candidate = (root / rel).resolve()
    if not _is_within(candidate, root):
        raise VaultPathError(
            f"resolved path {candidate} is outside vault root {root}"
        )
    return candidate.read_text(encoding="utf-8")


def _default_root() -> Path:
    env = os.environ.get("VAULT_ROOT")
    return Path(env) if env else DEFAULT_VAULT_ROOT


def _is_within(candidate: Path, root: Path) -> bool:
    try:
        candidate.relative_to(root)
    except ValueError:
        return False
    return True
