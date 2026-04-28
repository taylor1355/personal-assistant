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


class LinearError(RuntimeError):
    """Raised when the Linear CLI exits non-zero."""

    def __init__(self, returncode: int, stdout: str, stderr: str, cmd: list[str]) -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
        self.cmd = cmd
        super().__init__(
            f"linear-cli exited {returncode}: {stderr.strip() or stdout.strip() or '(no output)'}"
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
        # Skip the bash wrapper; call npx tsx directly so Windows doesn't
        # need bash in PATH for the agent to reach Linear. Resolve npx via
        # shutil.which because subprocess.run on Windows doesn't apply
        # PATHEXT resolution to bare command names (it would miss npx.cmd).
        npx = shutil.which("npx") or "npx"
        return [
            npx,
            "--prefix",
            str(self._linear_pm),
            "tsx",
            str(self._cli),
            *args,
        ]
