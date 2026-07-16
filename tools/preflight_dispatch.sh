#!/usr/bin/env bash
# Preflight for the /work skill (Phase 0). Run from the main worktree BEFORE
# dispatching any thread agents. Verifies that the shared tooling every agent
# will need is reachable, and that the test stack actually runs — so a shared
# blocker is caught once here instead of N times across N agent sandboxes.
#
# Exit 0 = GREEN (safe to dispatch). Exit 1 = RED (fix the blocker first).
#
# Usage: tools/preflight_dispatch.sh
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_DIR"

RED=0
_ok()   { printf '  [ok]   %s\n' "$1"; }
_bad()  { printf '  [RED]  %s\n' "$1" >&2; RED=1; }
_need() { # _need <label> <command...>
    local label="$1"; shift
    if "$@" >/dev/null 2>&1; then _ok "$label"; else _bad "$label — \`$*\` failed"; fi
}

echo "=== preflight: toolchain ==="
_need "git"            git --version
_need "gh CLI"         gh --version
_need "gh authed"      gh auth status
_need "uv"             uv --version
_need "node"           node --version
_need "npm"            npm --version
# Go is optional until the Go services have tests worth gating on.
if command -v go >/dev/null 2>&1; then _ok "go ($(go version | awk '{print $3}'))"; else printf '  [skip] go not on PATH (Go services not gated)\n'; fi

echo ""
echo "=== preflight: Linear reachable ==="
if bash "$PROJECT_DIR/tools/linear" whoami >/dev/null 2>&1; then
    _ok "tools/linear whoami"
else
    _bad "tools/linear whoami — Linear CLI unreachable (node_modules? LINEAR_API_KEY in .env?)"
fi

echo ""
echo "=== preflight: worktree bootstrap state (main) ==="
bash "$PROJECT_DIR/tools/setup_worktree.sh" --check || _bad "setup_worktree.sh --check errored"

echo ""
echo "=== preflight: unit suite runs (fast; the <5s gate) ==="
# Catches broken deps / import errors / pytest-config regressions that would
# make every agent's test run fail with opaque errors. Uses the real suite,
# which the testing rules require to finish in <5s.
PREFLIGHT_TMP=$(mktemp)
trap 'rm -f "$PREFLIGHT_TMP"' EXIT
if uv run --project agent pytest agent/tests -q >"$PREFLIGHT_TMP" 2>&1; then
    _ok "pytest agent/tests ($(grep -oE '[0-9]+ passed' "$PREFLIGHT_TMP" | head -1))"
else
    _bad "pytest agent/tests failed — see $PREFLIGHT_TMP (tail below)"
    tail -15 "$PREFLIGHT_TMP" >&2
fi

echo ""
if [[ "$RED" -eq 0 ]]; then
    echo "=== PREFLIGHT GREEN — safe to dispatch ==="
    exit 0
else
    echo "=== PREFLIGHT RED — fix the blocker(s) above before dispatching ===" >&2
    exit 1
fi
