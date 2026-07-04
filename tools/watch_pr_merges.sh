#!/usr/bin/env bash
# Ported from npc-simulation tools/ for the /work skill. Internal NPC-xxx
# references are original provenance (they document why the code is shaped
# this way); they are npc-simulation issue ids, not personal-assistant ones.
# Watch GitHub pull_request events for the current repo and emit one
# structured line per merge. Designed to be wrapped by the Monitor tool
# inside the /work skill so the orchestrator gets an event-driven signal
# instead of polling.
#
# Usage:
#   tools/watch_pr_merges.sh [owner/repo]
# If owner/repo is omitted, falls back to `gh repo view`.
#
# Output (stdout, line-buffered):
#   MERGED #<number> [<branch>] <title>
# Status lines (stderr):
#   STATUS: <message> — our own status (connecting, ready)
#   FATAL: <reason> — our prereq checks
#   <other text> — gh webhook forward's own stderr passes through unchanged
#     (e.g., "Forwarding Webhook events from GitHub..." once the websocket
#      is established, "[LOG] received event ..." per inbound event). This
#      is the operator's heartbeat that the stream is live during idle waits.
#
# Prereqs (checked at startup):
#   - gh CLI authenticated with `repo` scope (already standard)
#   - cli/gh-webhook extension installed
#   - jq on PATH
#
# Install the extension once: `gh extension install cli/gh-webhook`.

set -uo pipefail

REPO="${1:-$(gh repo view --json nameWithOwner -q .nameWithOwner 2>/dev/null || true)}"
if [ -z "$REPO" ]; then
    echo "FATAL: could not determine repo (pass owner/repo or run inside a gh-authed repo)" >&2
    exit 1
fi

if ! gh extension list 2>/dev/null | grep -q "cli/gh-webhook"; then
    echo "FATAL: cli/gh-webhook extension not installed. Run: gh extension install cli/gh-webhook" >&2
    exit 1
fi
if ! command -v jq >/dev/null 2>&1; then
    echo "FATAL: jq not on PATH. Install via 'winget install jqlang.jq' on Windows or" >&2
    echo "       your platform package manager. Standalone binary: https://jqlang.github.io/jq/download/" >&2
    exit 1
fi
# Match the scopes line specifically and require `repo` as a discrete token
# (not as a substring of `admin:repo_hook`, paths containing "repo", etc.).
# gh prints either `Token scopes: 'gist', 'repo', 'workflow'` (classic) or a
# similar comma-separated list. We anchor on the surrounding quotes/spaces.
if ! gh auth status 2>&1 | grep -i "scopes:" | grep -qE "(^|[ ,'])repo([ ,']|$)"; then
    echo "FATAL: gh token lacks 'repo' scope. Run: gh auth refresh -s repo" >&2
    exit 1
fi

echo "STATUS: connecting to $REPO webhook stream" >&2
echo "STATUS: ready — prereqs passed, launching gh webhook forward (its 'Forwarding...' line on stderr confirms the websocket is actually up)" >&2

gh webhook forward --events=pull_request --repo="$REPO" \
  | jq -rc --unbuffered '
      select(.action == "closed" and .pull_request.merged == true)
      | "MERGED #\(.pull_request.number) [\(.pull_request.head.ref)] \(.pull_request.title)"
    '
