"""Day-to-day continuity log for the memory substrate (PA-102).

Each substrate refresh appends a dated entry under
``00 - Assistant/Memory/continuity/YYYY-MM-DD.md`` recording what got done
(Linear completions, journal-detected completions) and any notable state
changes. Briefing/review/proactive layers read the recent entries to answer
"yesterday, what got done" instead of re-deriving it — or worse, surfacing
stale items because nothing remembered.

Entries are append-only per day: a second refresh on the same day appends a
new timestamped section rather than overwriting, so nothing is lost.

Days are bucketed in the user's *local* timezone (briefings reason about
"today"/"yesterday" locally); the clock is injectable via ``now`` so tests
don't depend on wall time.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path

from personal_assistant_agent.memory.completion import Completion


def _continuity_dir(memory_dir: Path) -> Path:
    return memory_dir / "continuity"


def write_continuity_entry(
    memory_dir: Path,
    *,
    now: datetime | None = None,
    day: date | None = None,
    completions: list[Completion] | None = None,
    notes: list[str] | None = None,
) -> Path:
    """Append a continuity entry for ``day`` (default: ``now``'s local date).

    ``now`` defaults to the local system time; pass it explicitly in tests.
    Completion lines are tagged with their Linear project
    (``- [Dev] PA-1: ...``) so readers can filter per project.

    Returns the path written. A refresh with nothing new still writes an
    entry ("no changes") so readers can distinguish "nothing happened" from
    "the substrate never ran."
    """
    now = now or datetime.now().astimezone()
    day = day if day is not None else now.date()
    completions = completions or []
    notes = notes or []
    cdir = _continuity_dir(memory_dir)
    cdir.mkdir(parents=True, exist_ok=True)
    path = cdir / f"{day.isoformat()}.md"

    stamp = now.strftime("%H:%M %Z")
    lines = [f"## {stamp} — substrate refresh", ""]
    if completions:
        lines.append("### Completed")
        for c in completions:
            lines.append(
                f"- [{c.project}] {c.identifier}: {c.title} → {c.state} ({c.source.value})"
            )
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


def read_recent_entries(
    memory_dir: Path,
    days: int = 2,
    *,
    now: datetime | None = None,
    project: str | None = None,
) -> str:
    """Return the last ``days`` days of continuity entries, newest first.

    ``now`` anchors "today" (default: local system time); pass it explicitly
    in tests. When ``project`` is given, completion lines for other projects
    are dropped — the daily briefing is personal-only, so it reads
    ``project="Personal"`` and never sees dev completions.

    Returns an empty string when the log is empty — callers treat that as
    "no continuity recorded yet," not as an error.
    """
    cdir = _continuity_dir(memory_dir)
    if not cdir.is_dir():
        return ""
    today = (now or datetime.now().astimezone()).date()
    chunks: list[str] = []
    for offset in range(days):
        day = today - timedelta(days=offset)
        path = cdir / f"{day.isoformat()}.md"
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8").strip()
        if project is not None:
            text = _filter_project(text, project)
        chunks.append(f"# {day.isoformat()}\n\n{text}")
    return "\n\n---\n\n".join(chunks)


def _filter_project(text: str, project: str) -> str:
    """Drop completion lines tagged for a different project.

    Completion lines look like ``- [Dev] PA-1: ...``; everything else
    (headers, notes) is kept.
    """
    kept: list[str] = []
    for line in text.splitlines():
        if line.startswith("- [") and not line.startswith(f"- [{project}]"):
            continue
        kept.append(line)
    return "\n".join(kept).strip()
