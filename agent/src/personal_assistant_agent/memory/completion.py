"""Completion awareness for the memory substrate (PA-102).

The staleness bug: briefings surfaced done-2025 todos because nothing
tracked what had *changed*. This module snapshots Linear issue states per
project and diffs consecutive snapshots, so the substrate knows exactly
which issues transitioned to Done/Cancelled since the last refresh —
"yesterday, what got done."

Snapshots are persisted to ``00 - Assistant/Memory/linear-snapshots.json``.
Journal/chat-detected completions (from the journal_agent's proposals) are
recorded separately via the continuity log; this module covers the Linear
side. Both feed the same continuity entries.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

# States that mean "this issue is finished, stop surfacing it."
TERMINAL_STATES = frozenset({"Done", "Done ", "Cancelled", "Canceled", "Duplicate"})


@dataclass(frozen=True)
class IssueState:
    """One issue's tracked state at snapshot time."""

    identifier: str  # e.g. "PA-102"
    title: str
    state: str  # Linear state name, e.g. "Todo", "In Progress", "Done"
    updated_at: str  # ISO-8601 as reported by Linear


@dataclass(frozen=True)
class Completion:
    """An issue that reached a terminal state between two snapshots."""

    identifier: str
    title: str
    state: str  # the terminal state it landed in
    source: str = "linear"  # "linear" or "journal"


def is_terminal(state: str) -> bool:
    """True when the state means the issue is finished."""
    return state.strip() in {s.strip() for s in TERMINAL_STATES}


def diff_snapshots(
    old: dict[str, IssueState],
    new: dict[str, IssueState],
) -> list[Completion]:
    """Return issues that became terminal between two snapshots.

    An issue counts as newly completed when it is terminal in ``new`` and
    was either absent from ``old`` (first seen already done — still worth
    noting once) or non-terminal in ``old``. Issues already terminal in
    ``old`` are not reported again — that's the anti-staleness core: each
    completion surfaces exactly once.
    """
    completions: list[Completion] = []
    for identifier, current in new.items():
        if not is_terminal(current.state):
            continue
        previous = old.get(identifier)
        if previous is None or not is_terminal(previous.state):
            completions.append(
                Completion(
                    identifier=identifier,
                    title=current.title,
                    state=current.state,
                )
            )
    return sorted(completions, key=lambda c: c.identifier)


def load_snapshots(memory_dir: Path) -> dict[str, dict[str, IssueState]]:
    """Load persisted snapshots: ``{project_name: {identifier: IssueState}}``.

    Returns an empty dict when nothing was persisted yet (first run).
    """
    path = memory_dir / "linear-snapshots.json"
    if not path.is_file():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return {
        project: {ident: IssueState(**s) for ident, s in states.items()}
        for project, states in data.items()
    }


def save_snapshots(
    memory_dir: Path,
    snapshots: dict[str, dict[str, IssueState]],
) -> None:
    """Persist snapshots for the next diff."""
    path = memory_dir / "linear-snapshots.json"
    data = {
        project: {ident: asdict(s) for ident, s in states.items()}
        for project, states in snapshots.items()
    }
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
