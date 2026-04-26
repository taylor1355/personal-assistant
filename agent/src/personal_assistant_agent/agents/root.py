"""Root-agent wake handler.

Routes per wake-reason to the appropriate subagent. Subagents do the
actual work; this module is dispatch + shared context.

Reads from: vault (today's journal section, todos, inbox).
Writes through: subagent invocations only.
Emits proposal action types: depends on routed subagent.
Triggers it serves: all (it's the entry point).
Escalates when: an unknown reason arrives → log warning, no-op exit.
"""
from __future__ import annotations

import os
import re
from datetime import UTC, date, datetime
from pathlib import Path
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from personal_assistant_agent.agents.intake_agent import IntakeResult, process_inbox
from personal_assistant_agent.agents.journal_agent import (
    DEFAULT_MODEL,
    detect_completed_todos,
)
from personal_assistant_agent.tools.linear_cli import LinearClient
from personal_assistant_agent.tools.proposal_enqueue import enqueue
from personal_assistant_agent.tools.vault_read import (
    DEFAULT_VAULT_ROOT,
    VaultPathError,
    read_vault_file,
)

if TYPE_CHECKING:
    from anthropic import Anthropic

TODOS_FILE = "02 - Todos/01 - Short Term Todos.md"
INBOX_FILE = "00 - Assistant/Inbox.md"

# Wake reasons accepted by ``handle_wake``. Others are logged + skipped.
JOURNAL_REASONS = frozenset({"journal", "test"})
INBOX_REASONS = frozenset({"inbox", "inbox_edit", "sms_inbound"})


def handle_wake(
    reason: str,
    *,
    vault_root: Path | None = None,
    proposals_dir: Path | None = None,
    now: datetime | None = None,
    timezone_name: str | None = None,
    client: Anthropic | None = None,
    model: str = DEFAULT_MODEL,
    linear: LinearClient | None = None,
) -> list[Path]:
    """Run a wake cycle. Returns paths of any emitted proposal files.

    Routes by ``reason``:

    - ``journal`` / ``test`` → journal_agent
    - ``inbox`` / ``inbox_edit`` / ``sms_inbound`` → intake_agent
    - anything else → no-op (caller should treat as a configuration bug)

    The Linear-only intake branch returns ``[]`` since auto-applied
    Linear creates don't emit proposal files yet (audit-log proposals
    will come once the executor is wired). Inspect side effects through
    the ``LinearClient`` instance.
    """
    vault_root = (vault_root or DEFAULT_VAULT_ROOT)
    now = now or datetime.now(UTC)
    tz_name = timezone_name or os.environ.get("USER_TIMEZONE", "UTC")

    if reason in JOURNAL_REASONS:
        return _run_journal(
            vault_root=vault_root,
            proposals_dir=proposals_dir,
            now=now,
            tz_name=tz_name,
            client=client,
            model=model,
        )

    if reason in INBOX_REASONS:
        if linear is None:
            raise ValueError(
                f"reason={reason!r} requires a LinearClient; pass linear=..."
            )
        _run_intake(
            vault_root=vault_root,
            linear=linear,
            client=client,
            model=model,
        )
        # Intake doesn't emit proposal files in v0.1; the LinearClient is
        # the audit trail until the executor lands.
        return []

    print(f"agent: wake reason={reason!r} not recognized — no-op")
    return []


def _run_journal(
    *,
    vault_root: Path,
    proposals_dir: Path | None,
    now: datetime,
    tz_name: str,
    client: Anthropic | None,
    model: str,
) -> list[Path]:
    today_local = now.astimezone(ZoneInfo(tz_name)).date()

    journal_path = f"01 - Journals/{today_local.year} Entries.md"
    journal_full = read_vault_file(journal_path, vault_root=vault_root)
    section = extract_journal_section(journal_full, today_local)
    if not section:
        # No entry for today yet — nothing to detect. Not an error.
        return []

    todos_text = read_vault_file(TODOS_FILE, vault_root=vault_root)

    proposals = detect_completed_todos(
        journal_text=section,
        todos_text=todos_text,
        todos_file_path=TODOS_FILE,
        now=now,
        client=client,
        model=model,
    )

    return [enqueue(p, proposals_dir=proposals_dir) for p in proposals]


def _run_intake(
    *,
    vault_root: Path,
    linear: LinearClient,
    client: Anthropic | None,
    model: str,
) -> IntakeResult:
    """Read inbox content and route through intake_agent.

    Returns the IntakeResult so CLI/callers can render it; ``handle_wake``
    discards the value for now and just runs for side effects.
    """
    try:
        inbox_text = read_vault_file(INBOX_FILE, vault_root=vault_root)
    except (FileNotFoundError, VaultPathError):
        # Empty inbox is the steady state when there's nothing new.
        return IntakeResult(items=[], linear_created=[], deferred=[], errors=[])

    if not inbox_text.strip():
        return IntakeResult(items=[], linear_created=[], deferred=[], errors=[])

    return process_inbox(
        inbox_text=inbox_text,
        linear=linear,
        client=client,
        model=model,
    )


_DATE_HEADING = re.compile(r"^# \d{1,2}-\d{1,2}\s*$")


def extract_journal_section(text: str, d: date) -> str:
    """Extract the content of today's section from a year-collated journal.

    The vault uses ``# M-DD`` or variants as section dividers. Returns text
    from the matching heading until the next date heading (or EOF), stripped.
    Empty string if today's heading isn't present.
    """
    candidates = {
        f"# {d.month}-{d.day:02d}",
        f"# {d.month:02d}-{d.day:02d}",
        f"# {d.month}-{d.day}",
        f"# {d.month:02d}-{d.day}",
    }
    in_section = False
    out: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if _DATE_HEADING.match(stripped):
            if in_section:
                break  # next section — stop collecting
            if stripped in candidates:
                in_section = True
            continue
        if in_section:
            out.append(line)
    return "\n".join(out).strip()
