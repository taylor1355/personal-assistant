"""PA value-layer tools as an MCP stdio server for the Hermes Agent harness.

Hermes (the harness) stays an unmodified upstream clone; the personal-assistant
tools live here, in this repo, and reach Hermes over MCP. Every tool registered
here lands in Hermes toolset ``mcp-pa-tools``, which the Hermes config locks down
via ``platform_toolsets`` (read + plan only). The orchestrator is never handed
Hermes' ``terminal``/``file`` toolsets, so it cannot mutate user state outside
these typed tools — the proposal-queue invariant, enforced by construction.

The existing stdlib-only helpers (``read_vault_file``, ``LinearClient``) are
loaded directly from the ``personal_assistant_agent`` package files, so this
server carries no dependency on the retired NeMo agent runtime.

Environment:
  PA_REPO_ROOT  a PA checkout containing ``tools/linear-pm`` + ``.env`` (Linear creds)
  VAULT_ROOT    the Obsidian vault root (read-only access)
"""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path
from types import ModuleType

from mcp.server.fastmcp import FastMCP

REPO_ROOT = Path(os.environ.get("PA_REPO_ROOT", "")).expanduser()
VAULT_ROOT = Path(os.environ.get("VAULT_ROOT", "")).expanduser()


def _load_module(name: str, path: Path) -> ModuleType:
    """Load a single .py file as a standalone module, bypassing package import.

    Avoids triggering ``personal_assistant_agent/__init__`` (which pulls the
    NeMo-based agent code); the two helpers we need import only stdlib.
    """
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {name} from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_env_file(repo_root: Path) -> None:
    """Populate os.environ from <repo>/.env (LINEAR_API_KEY, LINEAR_TEAM_KEY)."""
    env_path = repo_root / ".env"
    if not env_path.is_file():
        return
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_tools_dir = REPO_ROOT / "agent" / "src" / "personal_assistant_agent" / "tools"
_vault_read = _load_module("pa_vault_read", _tools_dir / "vault_read.py")
_linear_cli = _load_module("pa_linear_cli", _tools_dir / "linear_cli.py")

_load_env_file(REPO_ROOT)
_linear = _linear_cli.LinearClient(repo_root=REPO_ROOT)

mcp = FastMCP("pa-tools")


# --- Vault (read-only) ---

@mcp.tool()
def vault_read(path: str) -> str:
    """Read a UTF-8 file from the Obsidian vault. `path` is relative to the vault
    root, e.g. '01 - Journals/2026 Entries.md'. Read-only; traversal-guarded."""
    return _vault_read.read_vault_file(path, vault_root=VAULT_ROOT)


@mcp.tool()
def vault_list(subdir: str = ".") -> str:
    """List files and folders one level under a vault subdirectory (read-only).
    `subdir` is relative to the vault root; use '.' for the top level."""
    root = VAULT_ROOT.resolve()
    target = (root / subdir).resolve()
    if root != target and root not in target.parents:
        raise ValueError(f"{subdir!r} resolves outside the vault")
    if not target.is_dir():
        raise ValueError(f"{subdir!r} is not a directory under the vault")
    lines = [f"{'[dir] ' if p.is_dir() else '      '}{p.name}" for p in sorted(target.iterdir())]
    return "\n".join(lines) or "(empty)"


# --- Linear: reads ---

@mcp.tool()
def linear_board() -> str:
    """Linear board overview: issues grouped by state (In Progress / Todo / Backlog / ...)."""
    return _linear.status()


@mcp.tool()
def linear_todo() -> str:
    """All Todo-state Linear issues, sorted by priority."""
    return _linear.todo()


@mcp.tool()
def linear_next() -> str:
    """The single highest-priority unblocked Linear issue to work on next."""
    return _linear.next()


@mcp.tool()
def linear_issue(identifier: str) -> str:
    """Full details of one Linear issue, e.g. identifier='PA-12'."""
    return _linear.issue(identifier)


@mcp.tool()
def linear_search(query: str) -> str:
    """Search Linear issues by free-text query."""
    return _linear.search(query)


# --- Linear: planning writes (low-stakes, auto-applied per the architecture) ---

@mcp.tool()
def linear_create(title: str, description: str = "", priority: int | None = None,
                  labels: list[str] | None = None, state: str | None = None) -> str:
    """Create a Linear issue. priority: 1=Urgent .. 4=Low (0=None). labels/state by name."""
    return _linear.create(title=title, description=description, priority=priority,
                          labels=labels, state=state)


@mcp.tool()
def linear_comment(identifier: str, body: str) -> str:
    """Add a comment to a Linear issue."""
    return _linear.comment(identifier, body)


@mcp.tool()
def linear_set_state(state: str, identifiers: list[str]) -> str:
    """Move one or more issues to a state (e.g. 'Todo', 'In Progress', 'Backlog')."""
    return _linear.set_state(state, *identifiers)


@mcp.tool()
def linear_set_priority(priority: int, identifiers: list[str]) -> str:
    """Set priority (1=Urgent .. 4=Low, 0=None) on one or more issues."""
    return _linear.set_priority(priority, *identifiers)


@mcp.tool()
def linear_link(blocker: str, blocked: str) -> str:
    """Record that `blocker` blocks `blocked` (both Linear issue identifiers)."""
    return _linear.link(blocker, blocked)


if __name__ == "__main__":
    mcp.run()
