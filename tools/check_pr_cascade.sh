#!/bin/bash
# Ported from npc-simulation tools/ for the /work skill. Internal NPC-xxx
# references are original provenance (they document why the code is shaped
# this way); they are npc-simulation issue ids, not personal-assistant ones.
# PR cascade-impact shortlist.
#
# Given a just-merged PR and the currently-open PR set, scans the open PRs
# for reviewer feedback (inline comments + review/issue comment bodies) that
# references files the merge touched. Used by the /work skill's merge
# watcher (Phase 6b) to flag cross-PR cascades after each merge.
#
# Usage:
#   ./tools/check_pr_cascade.sh <merged-pr> [<open-pr>...]   # markdown to stdout
#   ./tools/check_pr_cascade.sh --json <merged-pr> [...]     # JSON to stdout
#   ./tools/check_pr_cascade.sh <merged-pr>                  # auto-discovers open PRs
#   ./tools/check_pr_cascade.sh --repo owner/name 142        # override current repo
#   ./tools/check_pr_cascade.sh --timeout 10 142             # widen per-PR fetch budget
#   ./tools/check_pr_cascade.sh -h | --help                  # show this usage block
#
# Output (default, markdown):
#   Per-PR sections listing HIGH-CONF intersections (inline comment .path
#   matches a merged file) and HEURISTIC intersections (review/issue body
#   regex match). PRs with no intersections are omitted. If nothing
#   intersects, prints 'No cross-PR impacts found.' to stdout.
#
# Exit codes:
#   0 — analysis ran (empty or non-empty result is fine)
#   1 — gh CLI error (auth, repo discovery, listing open PRs)
#   2 — merged-PR fetch failed (PR doesn't exist, timed out, etc.)
#   non-zero — argparse error (missing required arg, etc.)
#
# This is a SHORTLIST GENERATOR. The HEURISTIC matches are intentionally
# loose (any path-shaped substring in a comment body). Manual review of the
# shortlist remains the gate. The acceptance trade-off is documented in
# tools/README.md and NPC-667.

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

# Locate a WORKING Python 3. `command -v python3` is not enough on Windows,
# where a non-functional Microsoft Store stub shadows the name — so verify each
# candidate actually executes. Fall back to the project's uv-managed Python:
# this repo ships no standalone python3; real Python lives in agent/.venv, and
# check_pr_cascade.py is stdlib-only so any real interpreter runs it.
PYTHON=""
_py_works() { "$@" -c "import sys; sys.exit(0)" >/dev/null 2>&1; }
if _py_works python3; then
    PYTHON="python3"
elif _py_works python && python -c "import sys; sys.exit(0 if sys.version_info[0] >= 3 else 1)" 2>/dev/null; then
    PYTHON="python"
elif _py_works py -3; then
    PYTHON="py -3"
elif command -v uv >/dev/null 2>&1; then
    PYTHON="uv run --project agent python"
fi

if [[ -z "$PYTHON" ]]; then
    echo "Error: no working Python 3 found (tried python3/python/py; uv fallback unavailable)." >&2
    echo "       Install Python 3.10+ or uv and re-run." >&2
    exit 1
fi

# Short-circuit --help before exec'ing Python.
for arg in "$@"; do
    if [[ "$arg" == "-h" || "$arg" == "--help" ]]; then
        sed -n '2,/^set -/p' "$0" | sed 's/^# \{0,1\}//;$d'
        exit 0
    fi
done

cd "$PROJECT_DIR"
exec $PYTHON "$SCRIPT_DIR/check_pr_cascade.py" "$@"
