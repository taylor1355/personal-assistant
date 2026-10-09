"""Authoritative map of the vault's folder taxonomy (PA-102).

The daily-briefing agent once hallucinated ``06 - Learning`` when the real
folder was ``08 - Learning`` (``06`` is ``06 - Records``) because it had no
map of the vault's layout — it guessed. This module builds that map by
scanning the vault root, so every layer reads the same authoritative
structure instead of inventing paths.

The map is persisted to ``00 - Assistant/Memory/world-map.json`` and
refreshed by :func:`personal_assistant_agent.memory.substrate.refresh`.
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

# Folders the agent owns or that are infrastructure — still mapped (they're
# part of the world) but callers can filter them out when listing "content"
# folders for the user.
INFRA_FOLDERS = frozenset({"00 - Assistant", "00 - Proposals"})

# Matches a numeric prefix like "08 - " so "08 - Learning" normalizes to
# "learning" for lookup.
_PREFIX_RE = re.compile(r"^\d+\s*[-–—]\s*")


@dataclass(frozen=True)
class FolderEntry:
    """One top-level vault folder."""

    path: str  # exact folder name, e.g. "08 - Learning"
    name: str  # normalized lookup key, e.g. "learning"
    note_count: int  # markdown files directly inside (one level)
    infra: bool  # True for agent-owned / infrastructure folders


@dataclass(frozen=True)
class WorldMap:
    """The vault's folder taxonomy at a point in time."""

    generated_at: str  # ISO-8601 UTC
    folders: tuple[FolderEntry, ...]

    def to_json(self) -> str:
        return json.dumps(
            {"generated_at": self.generated_at,
             "folders": [asdict(f) for f in self.folders]},
            indent=2,
        )

    @staticmethod
    def from_json(raw: str) -> WorldMap:
        data = json.loads(raw)
        return WorldMap(
            generated_at=data["generated_at"],
            folders=tuple(FolderEntry(**f) for f in data["folders"]),
        )


def normalize_folder_name(folder: str) -> str:
    """Strip a numeric prefix and lowercase: ``08 - Learning`` -> ``learning``."""
    return _PREFIX_RE.sub("", folder).strip().lower()


def build_world_map(vault_root: Path) -> WorldMap:
    """Scan the vault root's top-level directories into a WorldMap.

    Only directories are mapped (files at the root are rare and not part of
    the taxonomy agents need). Hidden directories (``.obsidian``, ``.trash``)
    are skipped — they're app internals, not user geography.
    """
    root = vault_root.resolve()
    entries: list[FolderEntry] = []
    for child in sorted(root.iterdir(), key=lambda p: p.name.lower()):
        if not child.is_dir() or child.name.startswith("."):
            continue
        note_count = sum(
            1 for p in child.iterdir()
            if p.is_file() and p.suffix.lower() == ".md"
        )
        entries.append(
            FolderEntry(
                path=child.name,
                name=normalize_folder_name(child.name),
                note_count=note_count,
                infra=child.name in INFRA_FOLDERS,
            )
        )
    return WorldMap(
        generated_at=datetime.now(UTC).isoformat(),
        folders=tuple(entries),
    )


def find_folder(world_map: WorldMap, name: str) -> FolderEntry | None:
    """Look up a folder by a human name: ``find_folder(m, "learning")``.

    Matches against the normalized name, so "Learning", "learning", and
    "08 - Learning" all resolve to the real folder. Returns None when there
    is no match — callers should fall back to listing, not guessing.
    """
    key = normalize_folder_name(name)
    for folder in world_map.folders:
        if folder.name == key:
            return folder
    return None


def load_world_map(memory_dir: Path) -> WorldMap | None:
    """Load the persisted world-map, or None if it was never built."""
    path = memory_dir / "world-map.json"
    if not path.is_file():
        return None
    return WorldMap.from_json(path.read_text(encoding="utf-8"))
