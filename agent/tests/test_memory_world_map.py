"""Tests for the memory substrate's world-map (PA-102)."""
from __future__ import annotations

import json
from pathlib import Path

from personal_assistant_agent.memory.world_map import (
    FolderEntry,
    WorldMap,
    build_world_map,
    find_folder,
    load_world_map,
    normalize_folder_name,
)


def _vault(tmp_path: Path) -> Path:
    for folder in ["08 - Learning", "06 - Records", "00 - Assistant", "01 - Journals"]:
        d = tmp_path / folder
        d.mkdir()
        (d / "note.md").write_text("# note", encoding="utf-8")
    (tmp_path / ".obsidian").mkdir()  # hidden: must be skipped
    (tmp_path / "loose.md").write_text("x", encoding="utf-8")  # root file: not mapped
    return tmp_path


def test_build_maps_top_level_folders(tmp_path: Path) -> None:
    m = build_world_map(_vault(tmp_path))
    paths = [f.path for f in m.folders]
    assert "08 - Learning" in paths
    assert "06 - Records" in paths
    assert ".obsidian" not in paths
    assert "loose.md" not in paths


def test_note_counts_and_infra_flags(tmp_path: Path) -> None:
    m = build_world_map(_vault(tmp_path))
    by_path = {f.path: f for f in m.folders}
    assert by_path["08 - Learning"].note_count == 1
    assert by_path["08 - Learning"].infra is False
    assert by_path["00 - Assistant"].infra is True


def test_find_folder_resolves_human_names(tmp_path: Path) -> None:
    m = build_world_map(_vault(tmp_path))
    # The PA-102 bug: "learning" must resolve to "08 - Learning", never "06 - *".
    found = find_folder(m, "learning")
    assert found is not None
    assert found.path == "08 - Learning"
    assert find_folder(m, "08 - Learning") is not None
    assert find_folder(m, "nope") is None


def test_normalize_strips_numeric_prefix() -> None:
    assert normalize_folder_name("08 - Learning") == "learning"
    assert normalize_folder_name("Journals") == "journals"


def test_round_trip_json(tmp_path: Path) -> None:
    m = build_world_map(_vault(tmp_path))
    m2 = WorldMap.from_json(m.to_json())
    assert m2.folders == m.folders
    assert m2.generated_at == m.generated_at


def test_load_returns_none_when_missing(tmp_path: Path) -> None:
    assert load_world_map(tmp_path / "Memory") is None


def test_load_reads_persisted_map(tmp_path: Path) -> None:
    mem = tmp_path / "Memory"
    mem.mkdir()
    m = WorldMap(
        generated_at="2026-10-08T00:00:00+00:00",
        folders=(FolderEntry(path="08 - Learning", name="learning", note_count=3, infra=False),),
    )
    (mem / "world-map.json").write_text(m.to_json(), encoding="utf-8")
    loaded = load_world_map(mem)
    assert loaded is not None
    assert loaded.folders[0].path == "08 - Learning"
    assert json.loads((mem / "world-map.json").read_text())["folders"][0]["note_count"] == 3
