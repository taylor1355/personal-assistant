"""Substrate orchestration: refresh the memory store and read it back (PA-102).

This is the single entry point the briefing/review/proactive layers use.
``refresh()`` rebuilds the world-map, snapshots Linear issue states,
detects completions, and appends a continuity entry — one call keeps the
whole substrate current. ``get_context()`` returns everything a layer needs
in one shot: the world-map plus recent continuity.

The substrate lives under ``00 - Assistant/Memory/`` in the vault (the
agent's own working area, like briefings) — never user content, so no
proposal-queue involvement.

Which Linear projects feed completion awareness is per-user configuration
(``config/user.yaml`` → ``memory.projects``); callers pass them in — there
are no project names hardcoded here.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Protocol

from personal_assistant_agent.memory.completion import (
    Completion,
    IssueState,
    diff_snapshots,
    load_snapshots,
    save_snapshots,
)
from personal_assistant_agent.memory.continuity import (
    read_recent_entries,
    write_continuity_entry,
)
from personal_assistant_agent.memory.world_map import (
    WorldMap,
    build_world_map,
    load_world_map,
)

logger = logging.getLogger(__name__)

#: Subdirectory of ``00 - Assistant/`` holding all substrate files.
MEMORY_DIR_NAME = "Memory"


class IssueStateSource(Protocol):
    """Minimal surface refresh() needs from a Linear client."""

    def project_states(self, name: str) -> list[IssueState]: ...


@dataclass
class RefreshReport:
    """What a refresh did, for logging and for the continuity entry."""

    world_map_built: bool
    projects_snapshotted: tuple[str, ...] = ()
    completions: list[Completion] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def _memory_dir(vault_root: Path, assistant_root: str = "00 - Assistant") -> Path:
    d = vault_root.resolve() / assistant_root / MEMORY_DIR_NAME
    d.mkdir(parents=True, exist_ok=True)
    return d


def refresh(
    vault_root: Path,
    linear: IssueStateSource,
    *,
    projects: tuple[str, ...],
    assistant_root: str = "00 - Assistant",
    now: datetime | None = None,
) -> RefreshReport:
    """Rebuild the substrate: world-map, Linear snapshots, continuity entry.

    Safe to run on every wake — snapshots diff idempotently (already-seen
    completions are not re-reported; a first run seeds silently) and
    continuity entries append. ``projects`` comes from user config
    (``config/user.yaml`` → ``memory.projects``).
    """
    # Imported here, not at module top: tools.linear_cli imports
    # memory.completion, so a top-level import would be circular.
    from personal_assistant_agent.tools.linear_cli import LinearError

    memory_dir = _memory_dir(vault_root, assistant_root)
    report = RefreshReport(world_map_built=False)

    # 1. World-map: authoritative vault folder taxonomy.
    world_map = build_world_map(vault_root)
    (memory_dir / "world-map.json").write_text(world_map.to_json(), encoding="utf-8")
    report.world_map_built = True

    # 2. Linear snapshots + completion detection, per project.
    old_snapshots = load_snapshots(memory_dir)
    new_snapshots: dict[str, dict[str, IssueState]] = {}
    for project in projects:
        try:
            states = {s.identifier: s for s in linear.project_states(project)}
        except LinearError as e:
            logger.warning("snapshot of %r failed: %s", project, e)
            # Tagged with the project so _filter_project can drop it for
            # other-project readers (e.g. the personal briefing never sees
            # Dev snapshot failures).
            report.notes.append(f"[{project}] snapshot failed: {e}")
            continue
        new_snapshots[project] = states
        old = old_snapshots.get(project, {})
        for completion in diff_snapshots(old, states, project=project):
            report.completions.append(completion)
        report.projects_snapshotted += (project,)
    # Merge: keep projects we failed to snapshot this run at their old state.
    merged = {**old_snapshots, **new_snapshots}
    save_snapshots(memory_dir, merged)

    # 3. Continuity entry — always written, even when nothing changed.
    write_continuity_entry(
        memory_dir,
        now=now,
        completions=report.completions,
        notes=report.notes,
    )
    return report


@dataclass(frozen=True)
class SubstrateContext:
    """Everything a briefing/review/proactive layer needs from the substrate."""

    world_map: WorldMap | None
    continuity: str  # recent continuity entries, markdown ("" when none yet)

    def world_map_json(self) -> str:
        return self.world_map.to_json() if self.world_map else "(world-map not built yet)"


def get_context(
    vault_root: Path,
    *,
    days: int = 2,
    assistant_root: str = "00 - Assistant",
    project: str | None = None,
    now: datetime | None = None,
) -> SubstrateContext:
    """Read the substrate without mutating it. Cheap — call on every wake.

    When ``project`` is given, continuity entries are filtered to that
    project's completions (e.g. the personal daily briefing reads
    ``project="Personal"`` so dev completions never leak in).
    """
    memory_dir = _memory_dir(vault_root, assistant_root)
    return SubstrateContext(
        world_map=load_world_map(memory_dir),
        continuity=read_recent_entries(memory_dir, days=days, now=now, project=project),
    )
