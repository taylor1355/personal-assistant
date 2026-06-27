from __future__ import annotations

from pathlib import Path

import pytest

from personal_assistant_agent.tools.vault_read import (
    VaultPathError,
    is_within,
    read_vault_file,
    resolve_within,
)


def test_reads_file_under_root(tmp_path: Path) -> None:
    (tmp_path / "notes.md").write_text("hello", encoding="utf-8")
    assert read_vault_file("notes.md", vault_root=tmp_path) == "hello"


def test_reads_nested_file(tmp_path: Path) -> None:
    nested = tmp_path / "sub" / "dir"
    nested.mkdir(parents=True)
    (nested / "note.md").write_text("nested", encoding="utf-8")
    assert read_vault_file("sub/dir/note.md", vault_root=tmp_path) == "nested"


def test_rejects_absolute_path(tmp_path: Path) -> None:
    (tmp_path / "x.md").write_text("x", encoding="utf-8")
    with pytest.raises(VaultPathError):
        read_vault_file(str(tmp_path / "x.md"), vault_root=tmp_path)


def test_rejects_parent_traversal(tmp_path: Path) -> None:
    outside = tmp_path.parent / "escape.md"
    outside.write_text("escape", encoding="utf-8")
    try:
        with pytest.raises(VaultPathError):
            read_vault_file("../escape.md", vault_root=tmp_path)
    finally:
        outside.unlink(missing_ok=True)


def test_env_var_default(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "n.md").write_text("n", encoding="utf-8")
    monkeypatch.setenv("VAULT_ROOT", str(tmp_path))
    assert read_vault_file("n.md") == "n"


# --- resolve_within / is_within: the shared write-confinement boundary ---


def test_resolve_within_returns_path_for_nested(tmp_path: Path) -> None:
    got = resolve_within(tmp_path, "sub/dir/note.md")
    assert got == (tmp_path.resolve() / "sub" / "dir" / "note.md")


def test_resolve_within_allows_nonexistent_target(tmp_path: Path) -> None:
    # Callers that write rely on resolving a path that doesn't exist yet.
    assert resolve_within(tmp_path, "not/created/yet.md").name == "yet.md"


def test_resolve_within_rejects_parent_traversal(tmp_path: Path) -> None:
    with pytest.raises(VaultPathError):
        resolve_within(tmp_path, "../escape.md")


def test_resolve_within_rejects_absolute(tmp_path: Path) -> None:
    with pytest.raises(VaultPathError):
        resolve_within(tmp_path, str(tmp_path / "x.md"))


def test_is_within_true_for_nested_and_self(tmp_path: Path) -> None:
    area = (tmp_path / "00 - Assistant").resolve()
    assert is_within(area, area)
    assert is_within((area / "Briefings" / "x.md").resolve(), area)


def test_is_within_false_for_sibling_proposal_queue(tmp_path: Path) -> None:
    # The crux of the proposal-queue boundary: a file in the sibling
    # '00 - Proposals/' must NOT count as inside '00 - Assistant/', or the
    # agent's assistant_write could forge/approve proposals.
    area = (tmp_path / "00 - Assistant").resolve()
    proposal = (tmp_path / "00 - Proposals" / "evil.md").resolve()
    assert not is_within(proposal, area)


def test_is_within_false_for_prefix_sibling(tmp_path: Path) -> None:
    # Path-segment containment, not string prefixing: '00 - AssistantEvil'
    # shares a textual prefix with '00 - Assistant' but is a different folder.
    area = (tmp_path / "00 - Assistant").resolve()
    sibling = (tmp_path / "00 - AssistantEvil" / "x.md").resolve()
    assert not is_within(sibling, area)
