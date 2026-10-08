"""Memory / situational-awareness substrate (PA-102).

The one strong memory every layer (briefing, review, proactive) reads. It
holds three things:

- **World-map**: a stable, authoritative map of the vault's folder taxonomy,
  so agents stop guessing paths (the ``06 - Learning`` vs ``08 - Learning``
  bug). Built by scanning the vault; refreshed on demand.
- **Completion awareness**: snapshots of Linear issue states per project.
  Diffing consecutive snapshots surfaces what got done — the fix for
  briefings surfacing stale/done items, and the source of "yesterday, what
  got done" continuity.
- **Continuity log**: a dated markdown log under ``00 - Assistant/Memory/``
  recording completions and notable state changes, readable by any layer.

All substrate files live under the assistant-owned vault area
(``00 - Assistant/Memory/``), so they sync with the vault, are inspectable
by Taylor, and never touch user content — consistent with the proposal-queue
invariant (these are the agent's own working notes, like briefings).
"""
from __future__ import annotations

from personal_assistant_agent.memory.completion import (
    Completion,
    IssueState,
    diff_snapshots,
)
from personal_assistant_agent.memory.continuity import (
    read_recent_entries,
    write_continuity_entry,
)
from personal_assistant_agent.memory.substrate import (
    MEMORY_DIR_NAME,
    RefreshReport,
    get_context,
    refresh,
)
from personal_assistant_agent.memory.world_map import (
    WorldMap,
    build_world_map,
    find_folder,
    load_world_map,
)

__all__ = [
    "MEMORY_DIR_NAME",
    "Completion",
    "IssueState",
    "RefreshReport",
    "WorldMap",
    "build_world_map",
    "diff_snapshots",
    "find_folder",
    "get_context",
    "load_world_map",
    "read_recent_entries",
    "refresh",
    "write_continuity_entry",
]
