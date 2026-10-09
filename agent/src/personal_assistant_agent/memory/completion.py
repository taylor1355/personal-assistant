"""Completion awareness for the memory substrate (PA-102).

The staleness bug: briefings surfaced done-2025 todos because nothing
tracked what had *changed*. This module snapshots Linear issue states per
project and diffs consecutive snapshots, so the substrate knows exactly
which issues transitioned to Done/Cancelled since the last refresh —
"yesterday, what got done."

Terminality is keyed off Linear's workflow-state *type* ("completed" /
"canceled"), never the display name — names are user-renamable.

Snapshots are persisted to ``00 - Assistant/Memory/linear-snapshots.json``
(atomically: tempfile + rename, so a killed refresh can't corrupt them).

``CompletionSource.JOURNAL`` is reserved for journal/chat-detected
completions (from the journal_agent's proposals) — there is currently no
producer; wiring it up is tracked as PA-141 (tech-debt). This module covers
the Linear side only. Both feed the same continuity entries once wired.
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
from dataclasses import asdict, dataclass
from enum import StrEnum
from pathlib import Path

logger = logging.getLogger(__name__)


class StateType(StrEnum):
    """Linear workflow-state types. Mirrors the ``stateType`` field emitted by
    the ``project-states`` CLI command (tools/linear-pm/src/linear-cli.ts)."""

    COMPLETED = "completed"
    CANCELED = "canceled"
    STARTED = "started"
    UNSTARTED = "unstarted"
    BACKLOG = "backlog"
    TRIAGE = "triage"
    UNKNOWN = "unknown"


class CompletionSource(StrEnum):
    """Where a completion was detected."""

    LINEAR = "linear"
    JOURNAL = "journal"


@dataclass(frozen=True)
class IssueState:
    """One issue's tracked state at snapshot time."""

    identifier: str  # e.g. "PA-102"
    title: str
    state: str  # Linear state display name, e.g. "Todo", "In Progress", "Done"
    state_type: StateType = StateType.UNKNOWN
    updated_at: str = ""  # ISO-8601 as reported by Linear


@dataclass(frozen=True)
class Completion:
    """An issue that reached a terminal state between two snapshots."""

    identifier: str
    title: str
    project: str  # Linear project the issue belongs to ("Personal", "Dev", ...)
    state: str  # the terminal state display name it landed in
    source: CompletionSource = CompletionSource.LINEAR


def is_terminal(state_type: StateType) -> bool:
    """True when the workflow-state type means the issue is finished."""
    return state_type in (StateType.COMPLETED, StateType.CANCELED)


def diff_snapshots(
    old: dict[str, IssueState],
    new: dict[str, IssueState],
    *,
    project: str,
) -> list[Completion]:
    """Return issues that became terminal between two snapshots.

    An issue counts as newly completed when it is terminal in ``new`` and
    was non-terminal in ``old``. Issues already terminal in ``old`` are not
    reported again — that's the anti-staleness core: each completion
    surfaces exactly once.

    When ``old`` is empty (first run, new project, or corrupted snapshot)
    the new snapshot is seeded silently and nothing is reported: every
    already-Done issue would otherwise surface as a bogus "completion",
    reproducing the stale-done bug this module exists to fix.
    """
    if not old:
        return []
    completions: list[Completion] = []
    for identifier, current in new.items():
        if not is_terminal(current.state_type):
            continue
        previous = old.get(identifier)
        if previous is None or not is_terminal(previous.state_type):
            completions.append(
                Completion(
                    identifier=identifier,
                    title=current.title,
                    project=project,
                    state=current.state,
                )
            )
    return sorted(completions, key=lambda c: c.identifier)


def _coerce_state(raw: dict) -> IssueState:
    state_type = StateType.UNKNOWN
    if "state_type" in raw:
        try:
            state_type = StateType(raw["state_type"])
        except ValueError:
            logger.warning("unknown state_type %r; treating as unknown", raw["state_type"])
    return IssueState(
        identifier=raw["identifier"],
        title=raw["title"],
        state=raw["state"],
        state_type=state_type,
        updated_at=raw.get("updated_at", ""),
    )


def load_snapshots(memory_dir: Path) -> dict[str, dict[str, IssueState]]:
    """Load persisted snapshots: ``{project_name: {identifier: IssueState}}``.

    Returns an empty dict when nothing was persisted yet (first run) or the
    file is corrupt — the next refresh re-seeds silently (see
    :func:`diff_snapshots`), so a bad file can never wedge the substrate.
    Snapshots written before ``state_type`` existed are dropped for the same
    reason: without the type we can't tell terminal from not, and guessing
    from display names is exactly the fragility this module avoids.
    """
    path = memory_dir / "linear-snapshots.json"
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        snapshots: dict[str, dict[str, IssueState]] = {}
        for project, states in data.items():
            if not isinstance(states, dict):
                raise TypeError(f"project {project!r} snapshot is not a dict")
            coerced = {}
            for ident, raw in states.items():
                if "state_type" not in raw:
                    raise TypeError(
                        f"project {project!r} snapshot predates state_type; re-seeding"
                    )
                coerced[ident] = _coerce_state(raw)
            snapshots[project] = coerced
        return snapshots
    except (json.JSONDecodeError, TypeError, KeyError, AttributeError) as e:
        logger.warning("dropping unreadable snapshots file %s: %s", path, e)
        return {}


def _jsonable(obj):
    if isinstance(obj, StrEnum):
        return obj.value
    raise TypeError(f"not JSON serializable: {obj!r}")


def save_snapshots(
    memory_dir: Path,
    snapshots: dict[str, dict[str, IssueState]],
) -> None:
    """Persist snapshots for the next diff, atomically.

    Writes to a tempfile in the same directory then renames over the target,
    so a refresh killed mid-write can never leave a half-written file behind.
    """
    path = memory_dir / "linear-snapshots.json"
    data = {
        project: {ident: asdict(s) for ident, s in states.items()}
        for project, states in snapshots.items()
    }
    fd, tmp_name = tempfile.mkstemp(dir=str(memory_dir), prefix=".snapshots-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, default=_jsonable)
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise
