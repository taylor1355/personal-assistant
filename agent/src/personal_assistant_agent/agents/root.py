"""Root-agent wake handler.

v0 is single-subagent: every wake invokes ``journal_agent``. Trigger-based
routing lands when a second subagent joins (ARCHITECTURE.md#agent-shape).
"""
from __future__ import annotations

import os
import re
from datetime import date, datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from personal_assistant_agent.agents.journal_agent import (
    DEFAULT_MODEL,
    detect_completed_todos,
)
from personal_assistant_agent.tools.proposal_enqueue import enqueue
from personal_assistant_agent.tools.vault_read import DEFAULT_VAULT_ROOT, read_vault_file

if TYPE_CHECKING:
    from anthropic import Anthropic

TODOS_FILE = "02 - Todos/01 - Short Term Todos.md"


def handle_wake(
    reason: str,
    *,
    vault_root: Path | None = None,
    proposals_dir: Path | None = None,
    now: datetime | None = None,
    timezone_name: str | None = None,
    client: "Anthropic | None" = None,
    model: str = DEFAULT_MODEL,
) -> list[Path]:
    """Run a wake cycle. Returns paths of emitted proposal files.

    For v0 every wake runs ``journal_agent``; ``reason`` is recorded but
    does not route. Subsequent increments will route by reason.
    """
    del reason  # informational in v0; routing added with second subagent
    vault_root = vault_root or DEFAULT_VAULT_ROOT
    now = now or datetime.now(timezone.utc)
    tz_name = timezone_name or os.environ.get("USER_TIMEZONE", "UTC")
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
