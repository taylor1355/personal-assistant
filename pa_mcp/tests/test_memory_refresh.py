"""Regression test for PA-102 round-3: pa_tools_server must survive Linear failures.

The round-2 fix narrowed substrate.refresh's `except` to `LinearError`, but
pa_tools_server loaded linear_cli via _load_module under a second module name
(pa_linear_cli), creating a second LinearError class object. The narrowed
except never fired in production: one failing project escaped refresh() and
the MCP call errored out instead of returning a note.

The fix imports LinearClient from the package directly (single class
identity). This test makes _linear.project_states raise and asserts
memory_refresh returns a note instead of raising.
"""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest import mock

# Point the server at temp dirs before import (module reads env at load).
_TMP = Path(__file__).resolve().parent / "_tmp_server"
_TMP.mkdir(exist_ok=True)
os.environ.setdefault("PA_REPO_ROOT", str(Path(__file__).resolve().parent.parent.parent))
os.environ.setdefault("VAULT_ROOT", str(_TMP))

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "agent" / "src"))

import pa_tools_server  # noqa: E402
from personal_assistant_agent.tools.linear_cli import LinearError  # noqa: E402


class MemoryRefreshSurvivesLinearFailure(unittest.TestCase):
    def test_refresh_returns_note_when_project_states_raises(self) -> None:
        # Simulate a Linear failure (rate limit, renamed project, CLI error).
        with mock.patch.object(
            pa_tools_server._linear,
            "project_states",
            side_effect=LinearError("boom"),
        ):
            # Must not raise: the narrowed `except LinearError` in
            # substrate.refresh must catch the *same* LinearError class.
            result = pa_tools_server.memory_refresh.fn()
        self.assertIsInstance(result, str)
        self.assertIn("note:", result)
        self.assertIn("snapshot failed", result)


if __name__ == "__main__":
    unittest.main()
