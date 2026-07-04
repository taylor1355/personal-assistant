#!/usr/bin/env bash
# Bootstrap a fresh git worktree to a test-runnable state for personal-assistant.
#
# A freshly created `git worktree` lacks the un-committed artifacts the test
# stack needs:
#   - .env (secrets: LINEAR_API_KEY and friends) — never committed
#   - agent/.venv — the Python virtualenv `uv` builds from the lockfile
#   - tools/linear-pm/node_modules — npm deps for the Linear CLI
#
# This script regenerates all of the above. It is idempotent: running twice on
# an already-set-up worktree is a no-op per step. Windows Git-Bash / MSYS2
# friendly (paths from git are absolute, forward-slash).
#
# Usage:
#   tools/setup_worktree.sh                 # auto-detect a source .env from sibling worktrees
#   tools/setup_worktree.sh /path/to/main   # use an explicit source worktree for .env
#   tools/setup_worktree.sh --check         # report state without doing work
#   tools/setup_worktree.sh -h | --help     # show this usage block
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

CHECK_ONLY=false
SRC_WORKTREE=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        --check) CHECK_ONLY=true; shift ;;
        -h|--help) sed -n '2,/^set -/p' "$0" | sed 's/^# \{0,1\}//;$d'; exit 0 ;;
        -*) echo "Error: unknown flag: $1" >&2; exit 2 ;;
        *) SRC_WORKTREE="$1"; shift ;;
    esac
done

_header() { printf '\n=== %s ===\n' "$1"; }
_ok()     { printf '  [ok]   %s\n' "$1"; }
_todo()   { printf '  [todo] %s\n' "$1"; }
_do()     { printf '  [..]   %s\n' "$1"; }
_fail()   { printf '  [FAIL] %s\n' "$1" >&2; exit 1; }

# ---------- .env (copy from a source worktree) ----------
# Every worktree shares one repo but not the gitignored .env. Find a sibling
# worktree (or the explicit path) that has one and copy it.
_find_source_env() {
    if [[ -n "$SRC_WORKTREE" ]]; then
        [[ -f "$SRC_WORKTREE/.env" ]] && { echo "$SRC_WORKTREE/.env"; return; }
        _fail "no .env at the given source worktree: $SRC_WORKTREE"
    fi
    local path
    while IFS= read -r line; do
        [[ "$line" == worktree\ * ]] || continue
        path="${line#worktree }"
        [[ "$path" == "$PROJECT_DIR" ]] && continue
        [[ -f "$path/.env" ]] && { echo "$path/.env"; return; }
    done < <(git -C "$PROJECT_DIR" worktree list --porcelain)
    echo ""  # none found
}

_setup_env() {
    _header ".env"
    if [[ -f "$PROJECT_DIR/.env" ]]; then _ok ".env present"; return; fi
    if $CHECK_ONLY; then _todo ".env MISSING (would copy from a sibling worktree)"; return; fi
    local src; src="$(_find_source_env)"
    [[ -n "$src" ]] || _fail ".env missing and no sibling worktree has one — copy it in manually, or pass a source path"
    _do "copying .env from $src"
    cp "$src" "$PROJECT_DIR/.env"
    _ok ".env copied"
}

# ---------- Python deps (uv) ----------
_setup_python() {
    _header "Python deps (agent/.venv)"
    if [[ -d "$PROJECT_DIR/agent/.venv" ]]; then
        if $CHECK_ONLY; then _ok "agent/.venv present"; return; fi
    elif $CHECK_ONLY; then
        _todo "agent/.venv MISSING (would run: uv sync --project agent)"; return
    fi
    command -v uv >/dev/null 2>&1 || _fail "uv not on PATH — install uv (https://docs.astral.sh/uv/)"
    _do "uv sync --project agent"
    (cd "$PROJECT_DIR" && uv sync --project agent) || _fail "uv sync failed"
    _ok "Python deps synced"
}

# ---------- npm deps for the Linear CLI ----------
_setup_npm() {
    _header "Linear CLI deps (tools/linear-pm/node_modules)"
    if [[ -d "$PROJECT_DIR/tools/linear-pm/node_modules" ]]; then
        if $CHECK_ONLY; then _ok "node_modules present"; return; fi
    elif $CHECK_ONLY; then
        _todo "node_modules MISSING (would run: npm install in tools/linear-pm)"; return
    fi
    command -v npm >/dev/null 2>&1 || _fail "npm not on PATH — install Node.js"
    _do "npm install in tools/linear-pm/"
    (cd "$PROJECT_DIR/tools/linear-pm" && npm install --silent) || _fail "npm install failed"
    _ok "Linear CLI deps installed"
}

_setup_env
_setup_python
_setup_npm

if $CHECK_ONLY; then
    printf '\n=== check complete ===\n'
else
    printf '\n=== worktree ready ===\n'
fi
