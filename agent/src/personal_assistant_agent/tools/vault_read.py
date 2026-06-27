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


def resolve_within(root: Path, relative_path: str) -> Path:
    """Resolve ``relative_path`` under ``root``, rejecting any escape.

    Absolute paths, ``..`` traversal, and symlinks that resolve outside
    ``root`` all raise ``VaultPathError``. Returns the resolved absolute path,
    which need not exist yet — callers that write create it.

    This is the single place the vault's path confinement lives. Both the
    read tools and the assistant-area write tool route through it, so the
    boundary is enforced (and tested) once rather than re-implemented per
    call site where a subtle prefix bug could slip in.
    """
    rel = Path(relative_path)
    if rel.is_absolute():
        raise VaultPathError(f"path must be relative, got {relative_path!r}")
    root = root.resolve()
    candidate = (root / rel).resolve()
    if not is_within(candidate, root):
        raise VaultPathError(f"resolved path {candidate} is outside {root}")
    return candidate


def read_vault_file(relative_path: str, vault_root: Path | None = None) -> str:
    """Read a UTF-8 file under the vault root.

    ``relative_path`` is interpreted relative to the vault root. Absolute
    paths, ``..`` traversal, and symlinks pointing outside the vault are
    rejected — the tool is read-only, but a traversal bug would still leak
    host filesystem content into prompts.
    """
    root = vault_root or _default_root()
    return resolve_within(root, relative_path).read_text(encoding="utf-8")


def _default_root() -> Path:
    env = os.environ.get("VAULT_ROOT")
    return Path(env) if env else DEFAULT_VAULT_ROOT


def is_within(candidate: Path, root: Path) -> bool:
    """True if ``candidate`` is ``root`` itself or nested under it.

    Uses path-segment containment (``relative_to``), not string prefixing, so
    a sibling like ``00 - AssistantEvil`` is NOT considered within
    ``00 - Assistant``. Both paths should already be resolved.
    """
    try:
        candidate.relative_to(root)
    except ValueError:
        return False
    return True
