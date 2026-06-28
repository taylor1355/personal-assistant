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
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType

from mcp.server.fastmcp import FastMCP
from pydantic import ValidationError

REPO_ROOT = Path(os.environ.get("PA_REPO_ROOT", "")).expanduser()
VAULT_ROOT = Path(os.environ.get("VAULT_ROOT", "")).expanduser()
# Read-only Google Calendar (optional): a token written by scripts/
# google_oauth_setup.py. Absent → calendar_read degrades to a clear message.
GOOGLE_CALENDAR_TOKEN = os.environ.get("GOOGLE_CALENDAR_TOKEN", "")
GOOGLE_CALENDAR_ID = os.environ.get("GOOGLE_CALENDAR_ID", "primary")


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

# The proposal-emission helpers are real package modules (proposal_enqueue
# imports personal_assistant_agent.models). The package __init__ is trivial
# post-pivot, so putting agent/src on the path and importing them directly is
# clean — no _load_module dance needed here.
sys.path.insert(0, str(REPO_ROOT / "agent" / "src"))
from personal_assistant_agent import google_calendar  # noqa: E402
from personal_assistant_agent.tools.proposal_enqueue import (  # noqa: E402
    ProposalCollisionError,
    build_proposal,
    enqueue,
)

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


# --- Assistant-owned writes (briefings / digests — NOT user content) ---

ASSISTANT_ROOT = "00 - Assistant"


@mcp.tool()
def today() -> str:
    """Today's local date and weekday, e.g. '2026-06-22 (Monday)'. Use this to
    date briefings and reason about 'today'/'this week' — never guess the date."""
    return datetime.now().strftime("%Y-%m-%d (%A)")


@mcp.tool()
def calendar_read(days: int = 1) -> str:
    """Upcoming Google Calendar events for the next `days` days (default 1 =
    next 24h), time-ordered and read-only. Use it to ground the briefing and
    reason about what's coming up. Returns a clear message if calendar isn't
    configured; never writes — calendar changes go through `propose`."""
    try:
        from google.oauth2.credentials import Credentials  # lazy: optional dep
        from googleapiclient.discovery import build
    except ImportError:
        return "calendar unavailable: Google libraries not installed in the server env"
    if not GOOGLE_CALENDAR_TOKEN or not Path(GOOGLE_CALENDAR_TOKEN).is_file():
        return "calendar not configured: no token (run scripts/google_oauth_setup.py)"
    try:
        creds = Credentials.from_authorized_user_file(
            GOOGLE_CALENDAR_TOKEN, [google_calendar.CALENDAR_READONLY_SCOPE]
        )
        service = build("calendar", "v3", credentials=creds, cache_discovery=False)
        now = datetime.now(UTC)
        events = google_calendar.upcoming_events(
            service, now, now + timedelta(days=max(1, days)), calendar_id=GOOGLE_CALENDAR_ID
        )
    except Exception as e:
        # External-service boundary: surface a controlled message to the agent
        # rather than crashing the wake on a calendar/auth hiccup.
        return f"calendar read failed: {e}"
    return google_calendar.format_events(events)


@mcp.tool()
def assistant_write(path: str, content: str) -> str:
    """Write a UTF-8 file under the assistant-owned vault area ('00 - Assistant/...').
    For briefings, digests, and assistant notes. `path` is relative to the vault
    root and MUST be inside '00 - Assistant/'. Refuses anything outside it — user
    content is mutated only through proposals, never written directly. In
    particular it cannot reach the proposal queue ('00 - Proposals/'), so it
    cannot forge or approve a proposal."""
    try:
        target = _vault_read.resolve_within(VAULT_ROOT, path)
    except _vault_read.VaultPathError as e:
        raise ValueError(str(e)) from e
    assistant_area = (VAULT_ROOT / ASSISTANT_ROOT).resolve()
    if not _vault_read.is_within(target, assistant_area):
        raise ValueError(
            f"refused: {path!r} is outside '{ASSISTANT_ROOT}/' (user content needs a proposal)"
        )
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return f"wrote {target.relative_to(VAULT_ROOT.resolve())} ({len(content)} chars)"


# --- Proposals: the write path to user state (queued, never auto-applied) ---

# A top-level vault folder, deliberately OUTSIDE '00 - Assistant/'. assistant_write
# is confined to the assistant area, so it cannot reach this queue — the only way
# a proposal file comes to exist is this typed tool (which forces status=pending),
# and the only actor who can flip a proposal to 'approved' is the user editing in
# Obsidian. The separation is access-controlled, not honor-code.
PROPOSALS_ROOT = "00 - Proposals"
PROPOSALS_DIR = VAULT_ROOT / PROPOSALS_ROOT


@mcp.tool()
def propose(
    action: str,
    target: str,
    intent: str,
    reasoning: str,
    change: str,
    slug: str,
    mode: str | None = None,
    destination: str | None = None,
    notes: str | None = None,
) -> str:
    """Queue a proposed change to user state for the user to approve.

    This is the ONLY way to change user state. It does NOT apply the change —
    it writes a pending proposal (to '00 - Proposals/') the user reviews and
    approves in Obsidian; a separate privileged step applies approved ones.
    Emit ONE change per call (one todo, one event); split unrelated changes
    into separate proposals so each can be approved independently.

    action: one of vault_edit, vault_create, vault_move, vault_delete,
        calendar_create, calendar_update, calendar_delete, email_draft,
        email_label, email_archive.
    target: what the change acts on — a vault path relative to the vault root
        for vault_*, a calendar event id for calendar_*, a Gmail id for email_*.
        For vault_move this is the SOURCE path (file or folder).
    intent: one human sentence — what changes if the user approves.
    reasoning: why now. Quote the evidence (the journal line, the event) that
        triggered this; use [[wiki-links]] for vault sources.
    change: the exact change — full file content (vault_create, or vault_edit
        with mode='replace'), or the API payload (calendar_*/email_*). For
        vault_move/vault_delete, a one-line note of what moves/goes. Never
        describe a content change vaguely. (vault_edit mode='diff' is not yet
        applied — use mode='replace' with the full new file content.)
    slug: kebab-case, <=40 chars, summarizing the change (e.g.
        'check-off-gym-todo').
    mode: for vault_edit only — use 'replace' (full new content). Omit otherwise.
    destination: for vault_move only — the destination vault path (where target
        lands). Omit for every other action.
    notes: optional — ambiguity, alternatives considered, or follow-ups.
    """
    try:
        proposal = build_proposal(
            action=action,
            target=target,
            intent=intent,
            reasoning=reasoning,
            change=change,
            slug=slug,
            mode=mode,
            destination=destination,
            notes=notes,
            now=datetime.now(UTC),
        )
    except (ValueError, ValidationError) as e:
        raise ValueError(f"invalid proposal: {e}") from e
    try:
        path = enqueue(proposal, proposals_dir=PROPOSALS_DIR)
    except ProposalCollisionError as e:
        raise ValueError(
            f"a proposal already exists at {e}; choose a more specific slug and retry"
        ) from e
    return (
        f"queued proposal {path.name} (status: pending). It awaits your approval in "
        f"'{PROPOSALS_ROOT}/'; nothing changes until you approve it."
    )


if __name__ == "__main__":
    mcp.run()
