"""Day-to-day continuity log for the memory substrate (PA-102).

Each substrate refresh appends a dated entry under
``00 - Assistant/Memory/continuity/YYYY-MM-DD.md`` recording what got done
(Linear completions, journal-detected completions) and any notable state
changes. Briefing/review/proactive layers read the recent entries to answer
"yesterday, what got done" instead of re-deriving it — or worse, surfacing
stale items because nothing remembered.

Entries are append-only per day: a second refresh on the same day appends a
new timestamped section rather than overwriting, so nothing is lost.
"""
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from personal_assistant_agent.memory.completion import Completion


def _continuity_dir(memory_dir: Path) -> Path:
    return memory_dir / "continuity"


def write_continuity_entry(
    memory_dir: Path,
    *,
    day: date | None = None,
    completions: list[Completion] | None = None,
    notes: list[str] | None = None,
) -> Path:
    """Append a continuity entry for ``day`` (default: today UTC).

    Returns the path written. A refresh with nothing new still writes an
    entry ("no changes") so readers can distinguish "nothing happened" from
    "the substrate never ran."
    """
    day = day or datetime.now(UTC).date()
    completions = completions or []
    notes = notes or []
    cdir = _continuity_dir(memory_dir)
    cdir.mkdir(parents=True, exist_ok=True)
    path = cdir / f"{day.isoformat()}.md"

    stamp = datetime.now(UTC).strftime("%H:%M UTC")
    lines = [f"## {stamp} — substrate refresh", ""]
    if completions:
        lines.append("### Completed")
        for c in completions:
            lines.append(f"- {c.identifier}: {c.title} → {c.state} ({c.source})")
        lines.append("")
    if notes:
        lines.append("### Notes")
        for n in notes:
            lines.append(f"- {n}")
        lines.append("")
    if not completions and not notes:
        lines.append("No changes since the last refresh.")
        lines.append("")

    with path.open("a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return path


def read_recent_entries(memory_dir: Path, days: int = 2) -> str:
    """Return the last ``days`` days of continuity entries, newest first.

    Returns an empty string when the log is empty — callers treat that as
    "no continuity recorded yet," not as an error.
    """
    cdir = _continuity_dir(memory_dir)
    if not cdir.is_dir():
        return ""
    today = datetime.now(UTC).date()
    chunks: list[str] = []
    for offset in range(days):
        day = today - timedelta(days=offset)
        path = cdir / f"{day.isoformat()}.md"
        if path.is_file():
            chunks.append(f"# {day.isoformat()}\n\n{path.read_text(encoding='utf-8').strip()}")
    return "\n\n---\n\n".join(chunks)
