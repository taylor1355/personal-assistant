from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from personal_assistant_agent.tools.linear_cli import LinearClient, LinearError


@pytest.fixture
def fake_repo(tmp_path: Path) -> Path:
    """Minimal directory shaped like the repo so LinearClient passes its file check."""
    cli = tmp_path / "tools" / "linear-pm" / "src" / "linear-cli.ts"
    cli.parent.mkdir(parents=True)
    cli.write_text("// stub", encoding="utf-8")
    return tmp_path


@pytest.fixture
def fake_run(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Replace subprocess.run with a recorder. Returns the list of captured calls."""
    calls: list[dict[str, Any]] = []

    def _fake(cmd, **kwargs):  # type: ignore[no-untyped-def]
        calls.append({"cmd": list(cmd), **kwargs})
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr(subprocess, "run", _fake)
    return calls


# --- Construction ---


def test_constructor_uses_env_when_args_missing(
    fake_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LINEAR_API_KEY", "lin_api_xyz")
    monkeypatch.setenv("LINEAR_TEAM_KEY", "ZZ")
    c = LinearClient(repo_root=fake_repo)
    assert c._api_key == "lin_api_xyz"
    assert c._team_key == "ZZ"


def test_constructor_args_override_env(
    fake_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LINEAR_API_KEY", "from_env")
    c = LinearClient(repo_root=fake_repo, api_key="explicit", team_key="EX")
    assert c._api_key == "explicit"
    assert c._team_key == "EX"


def test_constructor_defaults_team_key_to_PA(
    fake_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("LINEAR_TEAM_KEY", raising=False)
    c = LinearClient(repo_root=fake_repo, api_key="k")
    assert c._team_key == "PA"


def test_constructor_raises_when_no_api_key(
    fake_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("LINEAR_API_KEY", raising=False)
    with pytest.raises(ValueError):
        LinearClient(repo_root=fake_repo)


def test_constructor_raises_when_cli_missing(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        LinearClient(repo_root=tmp_path, api_key="k")


# --- Command shaping ---


def test_command_uses_npx_tsx(fake_repo: Path) -> None:
    c = LinearClient(repo_root=fake_repo, api_key="k")
    cmd = c._command("status")
    assert cmd[0] == "npx"
    assert cmd[1] == "--prefix"
    assert cmd[2].endswith("linear-pm")
    assert cmd[3] == "tsx"
    assert cmd[4].endswith("linear-cli.ts")
    assert cmd[5] == "status"


def test_run_passes_api_key_and_team_key_via_env(
    fake_repo: Path, fake_run: list[dict[str, Any]]
) -> None:
    c = LinearClient(repo_root=fake_repo, api_key="lin_api_x", team_key="PA")
    c.status()
    env = fake_run[0]["env"]
    assert env["LINEAR_API_KEY"] == "lin_api_x"
    assert env["LINEAR_TEAM_KEY"] == "PA"


def test_run_uses_repo_root_as_cwd(
    fake_repo: Path, fake_run: list[dict[str, Any]]
) -> None:
    c = LinearClient(repo_root=fake_repo, api_key="k")
    c.status()
    assert fake_run[0]["cwd"] == str(fake_repo)


# --- Read methods ---


@pytest.mark.parametrize(
    "method,args,expected_tail",
    [
        ("whoami", (), ["whoami"]),
        ("status", (), ["status"]),
        ("todo", (), ["todo"]),
        ("next", (), ["next"]),
        ("blocked", (), ["blocked"]),
        ("search", ("test query",), ["search", "test query"]),
        ("issue", ("PA-42",), ["issue", "PA-42"]),
        ("project", ("Vault Cleanup",), ["project", "Vault Cleanup"]),
    ],
)
def test_read_methods_pass_args_through(
    fake_repo: Path,
    fake_run: list[dict[str, Any]],
    method: str,
    args: tuple,
    expected_tail: list[str],
) -> None:
    c = LinearClient(repo_root=fake_repo, api_key="k")
    getattr(c, method)(*args)
    assert fake_run[0]["cmd"][-len(expected_tail):] == expected_tail


# --- Write methods ---


def test_create_sends_json_on_stdin(
    fake_repo: Path, fake_run: list[dict[str, Any]]
) -> None:
    c = LinearClient(repo_root=fake_repo, api_key="k")
    c.create(
        title="Test issue",
        description="Body",
        priority=2,
        labels=["feature", "agent"],
        state="Todo",
    )
    call = fake_run[0]
    assert call["cmd"][-1] == "create"
    payload = json.loads(call["input"])
    assert payload == {
        "title": "Test issue",
        "description": "Body",
        "priority": 2,
        "labels": ["feature", "agent"],
        "state": "Todo",
    }


def test_create_omits_optional_fields(
    fake_repo: Path, fake_run: list[dict[str, Any]]
) -> None:
    c = LinearClient(repo_root=fake_repo, api_key="k")
    c.create(title="Bare title")
    payload = json.loads(fake_run[0]["input"])
    assert payload == {"title": "Bare title", "description": ""}


def test_update_includes_identifier_in_payload(
    fake_repo: Path, fake_run: list[dict[str, Any]]
) -> None:
    c = LinearClient(repo_root=fake_repo, api_key="k")
    c.update("PA-7", priority=1, state="In Progress")
    payload = json.loads(fake_run[0]["input"])
    assert payload == {"identifier": "PA-7", "priority": 1, "state": "In Progress"}


def test_pickup_supports_multiple_ids(
    fake_repo: Path, fake_run: list[dict[str, Any]]
) -> None:
    c = LinearClient(repo_root=fake_repo, api_key="k")
    c.pickup("PA-1", "PA-2", "PA-3")
    assert fake_run[0]["cmd"][-4:] == ["pickup", "PA-1", "PA-2", "PA-3"]


def test_done_passes_through(fake_repo: Path, fake_run: list[dict[str, Any]]) -> None:
    c = LinearClient(repo_root=fake_repo, api_key="k")
    c.done("PA-9")
    assert fake_run[0]["cmd"][-2:] == ["done", "PA-9"]


def test_set_state_with_multiword_state(
    fake_repo: Path, fake_run: list[dict[str, Any]]
) -> None:
    c = LinearClient(repo_root=fake_repo, api_key="k")
    c.set_state("In Progress", "PA-1", "PA-2")
    # The CLI's set-state handler accepts multi-word state followed by IDs.
    assert fake_run[0]["cmd"][-4:] == ["set-state", "In Progress", "PA-1", "PA-2"]


def test_set_priority_stringifies_int(
    fake_repo: Path, fake_run: list[dict[str, Any]]
) -> None:
    c = LinearClient(repo_root=fake_repo, api_key="k")
    c.set_priority(2, "PA-1")
    assert fake_run[0]["cmd"][-3:] == ["set-priority", "2", "PA-1"]


def test_comment_routes_body_through_stdin(
    fake_repo: Path, fake_run: list[dict[str, Any]]
) -> None:
    c = LinearClient(repo_root=fake_repo, api_key="k")
    body = "Multiline\nbody with\nspecial \"chars\""
    c.comment("PA-5", body)
    call = fake_run[0]
    assert call["cmd"][-3:] == ["comment", "PA-5", "-"]
    assert call["input"] == body


def test_link_unlink_pass_args_in_order(
    fake_repo: Path, fake_run: list[dict[str, Any]]
) -> None:
    c = LinearClient(repo_root=fake_repo, api_key="k")
    c.link("PA-5", "PA-12")
    c.unlink("PA-5", "PA-12")
    assert fake_run[0]["cmd"][-3:] == ["link", "PA-5", "PA-12"]
    assert fake_run[1]["cmd"][-3:] == ["unlink", "PA-5", "PA-12"]


# --- Errors ---


def test_nonzero_exit_raises_LinearError(
    fake_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _fake(cmd, **kwargs):  # type: ignore[no-untyped-def]
        return subprocess.CompletedProcess(args=cmd, returncode=2, stdout="", stderr="boom")

    monkeypatch.setattr(subprocess, "run", _fake)
    c = LinearClient(repo_root=fake_repo, api_key="k")
    with pytest.raises(LinearError) as excinfo:
        c.status()
    assert excinfo.value.returncode == 2
    assert "boom" in str(excinfo.value)


def test_LinearError_carries_stdout_and_stderr(
    fake_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _fake(cmd, **kwargs):  # type: ignore[no-untyped-def]
        return subprocess.CompletedProcess(
            args=cmd, returncode=1, stdout="partial output", stderr=""
        )

    monkeypatch.setattr(subprocess, "run", _fake)
    c = LinearClient(repo_root=fake_repo, api_key="k")
    with pytest.raises(LinearError) as excinfo:
        c.status()
    assert excinfo.value.stdout == "partial output"


def test_returns_stdout_on_success(
    fake_repo: Path, fake_run: list[dict[str, Any]]
) -> None:
    c = LinearClient(repo_root=fake_repo, api_key="k")
    out = c.status()
    assert out == "ok"
