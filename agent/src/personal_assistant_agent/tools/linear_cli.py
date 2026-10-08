"""Python wrapper around ``tools/linear`` (the TypeScript Linear CLI).

The CLI lives at ``<repo_root>/tools/linear-pm/src/linear-cli.ts`` and is
invoked through ``npx tsx``. We bypass the bash wrapper (``tools/linear``)
because Windows doesn't honor shebangs reliably from ``subprocess.run``;
calling ``npx`` directly works cross-platform as long as Node is on PATH.

Output is the CLI's stdout, returned as a string. The agent typically
hands these strings to an LLM for reasoning rather than parsing them
mechanically. Writes that report success/failure on the last line can
be checked by the caller; if the CLI exits non-zero, ``LinearError`` is
raised with stdout + stderr captured.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from personal_assistant_agent.memory.completion import IssueState, StateType


class LinearError(RuntimeError):
    """Raised when the Linear CLI exits non-zero, or its output is unparseable."""

    def __init__(self, returncode: int, stdout: str, stderr: str, cmd: list[str]) -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
        self.cmd = cmd
        super().__init__(
            f"linear-cli exited {returncode}: {stderr.strip() or stdout.strip() or '(no output)'}"
        )


class ProjectStateLine(BaseModel):
    """One JSONL record from ``linear project-states``.

    TS mirror: tools/linear-pm/src/linear-cli.ts :: ProjectStateLine — the
    field names must stay in sync (the audit skill checks this boundary).
    ``state_type`` is kept as a string here and coerced to
    :class:`StateType` on conversion: an unfamiliar type from a future Linear
    schema becomes ``UNKNOWN``, never a crash.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    identifier: str
    title: str
    state: str
    state_type: str = Field(alias="stateType")
    updated_at: str = Field(alias="updatedAt")

    def to_issue_state(self) -> IssueState:
        try:
            state_type = StateType(self.state_type)
        except ValueError:
            state_type = StateType.UNKNOWN
        return IssueState(
            identifier=self.identifier,
            title=self.title,
            state=self.state,
            state_type=state_type,
            updated_at=self.updated_at,
        )


class LinearClient:
    """Thin wrapper exposing one method per CLI command.

    All methods return the CLI's stdout as a string. Auto-applied write
    methods (``create``, ``update``, ``pickup``, ``done``, ``comment``,
    ``link``, ``unlink``, ``set_state``, ``set_priority``) are still
    invocations the agent must wrap in a proposal file for audit, per
    ``docs/ARCHITECTURE.md`` — this class does not enforce that; it's the
    transport, not the policy.
    """

    def __init__(
        self,
        *,
        repo_root: Path,
        api_key: str | None = None,
        team_key: str | None = None,
    ) -> None:
        self._repo_root = repo_root
        self._linear_pm = repo_root / "tools" / "linear-pm"
        self._cli = self._linear_pm / "src" / "linear-cli.ts"
        if not self._cli.is_file():
            raise FileNotFoundError(
                f"Linear CLI source not found at {self._cli}. "
                "Did you run `npm install` in tools/linear-pm/?"
            )
        self._api_key = api_key or os.environ.get("LINEAR_API_KEY", "")
        self._team_key = team_key or os.environ.get("LINEAR_TEAM_KEY", "PA")
        if not self._api_key:
            raise ValueError(
                "LINEAR_API_KEY is not set (pass api_key=... or set the env var)."
            )

    # --- Reads ---

    def whoami(self) -> str:
        return self._run("whoami")

    def status(self) -> str:
        return self._run("status")

    def todo(self) -> str:
        return self._run("todo")

    def next(self) -> str:
        return self._run("next")

    def blocked(self) -> str:
        return self._run("blocked")

    def search(self, query: str) -> str:
        return self._run("search", query)

    def issue(self, identifier: str) -> str:
        return self._run("issue", identifier)

    def project(self, name: str) -> str:
        return self._run("project", name)

    def project_states(self, name: str) -> list[IssueState]:
        """Structured issue states for a project (PA-102 completion snapshots).

        Calls the ``project-states`` CLI command, which emits one JSON object
        per line: ``{identifier, title, state, stateType, updatedAt}``.
        Unparseable lines raise :class:`LinearError` with the offending line
        attached — a corrupt CLI contract must fail loudly, not silently
        drop issues from the snapshot.
        """
        cmd = ["project-states", name]
        states: list[IssueState] = []
        for lineno, line in enumerate(self._run(*cmd).splitlines(), start=1):
            text = line.strip()
            if not text:
                continue
            try:
                parsed = ProjectStateLine(**json.loads(text))
            except (json.JSONDecodeError, ValidationError) as e:
                raise LinearError(
                    -1,
                    text,
                    f"unparseable project-states line {lineno}: {e}",
                    cmd,
                ) from e
            states.append(parsed.to_issue_state())
        return states

    # --- Auto-applied writes ---

    def create(
        self,
        *,
        title: str,
        description: str = "",
        priority: int | None = None,
        labels: list[str] | None = None,
        state: str | None = None,
    ) -> str:
        """Create an issue. Pass labels/state by their string names."""
        payload: dict[str, Any] = {"title": title, "description": description}
        if priority is not None:
            payload["priority"] = priority
        if labels:
            payload["labels"] = labels
        if state:
            payload["state"] = state
        # Use the JSON-stdin path for safer multiline / quote handling.
        return self._run("create", stdin=json.dumps(payload))

    def update(self, identifier: str, **fields: Any) -> str:
        """Update an existing issue. Allowed fields: title, description,
        priority, state, labels."""
        payload = dict(fields)
        payload["identifier"] = identifier
        return self._run("update", stdin=json.dumps(payload))

    def pickup(self, *identifiers: str) -> str:
        return self._run("pickup", *identifiers)

    def done(self, *identifiers: str) -> str:
        return self._run("done", *identifiers)

    def set_state(self, state: str, *identifiers: str) -> str:
        return self._run("set-state", state, *identifiers)

    def set_priority(self, priority: int | str, *identifiers: str) -> str:
        return self._run("set-priority", str(priority), *identifiers)

    def comment(self, identifier: str, body: str) -> str:
        # Multiline-safe: route the body through stdin via the "-" sentinel.
        return self._run("comment", identifier, "-", stdin=body)

    def link(self, blocker: str, blocked: str) -> str:
        return self._run("link", blocker, blocked)

    def unlink(self, blocker: str, blocked: str) -> str:
        return self._run("unlink", blocker, blocked)

    # --- Plumbing ---

    def _run(self, *args: str, stdin: str | None = None) -> str:
        cmd = self._command(*args)
        env = os.environ.copy()
        env["LINEAR_API_KEY"] = self._api_key
        env["LINEAR_TEAM_KEY"] = self._team_key
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            cwd=str(self._repo_root),
            env=env,
            input=stdin,
            check=False,
        )
        if result.returncode != 0:
            raise LinearError(result.returncode, result.stdout, result.stderr, cmd)
        return result.stdout

    def _command(self, *args: str) -> list[str]:
        # Invoke tsx's CLI through `node` directly, NOT through `npx`. On
        # Windows `npx` resolves to npx.cmd, and spawning a .cmd from a
        # console-less parent (the long-running gateway process) stalls the
        # call to 60s+ even though it's ~3.6s from a normal shell. `node` is a
        # real .exe, so `node <tsx-cli> <linear-cli.ts>` skips the cmd.exe
        # layer and stays fast in every spawn context.
        node = shutil.which("node") or "node"
        tsx_cli = self._linear_pm / "node_modules" / "tsx" / "dist" / "cli.mjs"
        return [
            node,
            str(tsx_cli),
            str(self._cli),
            *args,
        ]
