from __future__ import annotations

from pathlib import Path

import pytest

from personal_assistant_agent.tools.vault_read import VaultPathError, read_vault_file


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
