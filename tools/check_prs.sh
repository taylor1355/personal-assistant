#!/bin/bash
# Ported from npc-simulation tools/ for the /work skill. Internal NPC-xxx
# references are original provenance (they document why the code is shaped
# this way); they are npc-simulation issue ids, not personal-assistant ones.
# Walk full reviewer history for one or more PRs and report disposition status.
#
# Usage: ./tools/check_prs.sh [--repo OWNER/REPO] <PR numbers...>
# Example: ./tools/check_prs.sh 109 110
#          ./tools/check_prs.sh --repo taylor1355/other-repo 17   # a sibling repo's PR
#
# --repo targets a PR in a different repository than the current directory
# (e.g. a cross-repo stacked change). It exists so you NEVER hand-roll a repo
# override: substituting the REPO= line with sed silently falls back to the cwd
# repo when it fails to match, and then queries an unrelated same-numbered PR —
# the exact silent-wrong-repo trap that once made an open PR read as MERGED.
#
# For each PR, prints:
#   - merge state (MERGED / OPEN / CONFLICTING etc.)
#   - every reviewer comment from FULL history (no --since filtering)
#   - disposition per comment: [OPEN] or [DISPOSITIONED]
#     determined by whether the PR author has posted a reply containing
#     FIXED / DECLINED / DEFERRED in the same inline-comment thread (for
#     inline comments) or as a later top-level comment (for top-level
#     reviews).
#
# Empty output from --since-style filtering is unsafe — it hides
# pre-existing OPEN comments. This tool walks full history every time so
# that "no OPEN entries" is a real signal, not a filter artifact.
#
# Implementation note: uses `gh ... --jq` throughout (gh ships with
# bundled jq) so the script works on platforms where standalone jq
# isn't installed (e.g., git-bash on Windows).

# Optional --repo OWNER/REPO override (must precede the PR numbers). Explicit and
# fail-loud: if given without a value we error rather than silently fall through
# to the cwd repo.
REPO=""
if [ "${1:-}" = "--repo" ]; then
    REPO="${2:-}"
    if [ -z "$REPO" ]; then
        echo "Error: --repo requires an OWNER/REPO argument" >&2
        exit 1
    fi
    if [[ "$REPO" != */* ]]; then
        # A non-OWNER/REPO value (e.g. `--repo 17`) would otherwise be accepted,
        # consume the only token via shift, and run against a bogus repo — the
        # silent-wrong-target path this flag exists to eliminate.
        echo "Error: --repo expects OWNER/REPO (got '$REPO')" >&2
        exit 1
    fi
    shift 2
fi

# Pre-loop setup: check `gh` auth BEFORE enabling strict mode so the
# guard isn't dead code. Under `set -eu`, a failing command-substitution
# would exit the script before the `if [ -z ... ]` check can run.
if [ -z "$REPO" ]; then
    REPO=$(gh repo view --json nameWithOwner -q .nameWithOwner 2>/dev/null || true)
fi
if [ -z "$REPO" ]; then
    echo "Error: Could not determine repo (pass --repo OWNER/REPO, or run inside a gh-authenticated repo)" >&2
    exit 1
fi

# Require at least one PR number. Without this, an empty arg list — or a
# malformed --repo that consumed the only token — would exit 0 with no output,
# silently masking that nothing was reviewed (the exact missed-feedback class).
if [ "$#" -eq 0 ]; then
    echo "Error: no PR numbers given" >&2
    echo "Usage: $(basename "$0") [--repo OWNER/REPO] <PR numbers...>" >&2
    exit 1
fi

AUTHOR=$(gh api user --jq .login 2>/dev/null || echo "")
if [ -z "$AUTHOR" ]; then
    # AUTHOR="" silently disables disposition resolution — the worst
    # failure mode for this tool, since every comment would be reported
    # as [OPEN] regardless of actual reply state. Warn loudly.
    echo "Warning: could not determine gh user (gh api user failed) — disposition resolution disabled; all comments will show [OPEN]" >&2
fi
# A comment counts as a (hideable) agent disposition only when it STRUCTURALLY
# leads with one — never on a free-floating substring. The agent posts dispositions
# in two shapes, and the pattern matches exactly those:
#   1. per-comment inline replies that lead with a token, optionally bold/italic:
#      `**FIXED** — abc123`, `FIXED: ...`, `DEFERRED NPC-42`
#   2. top-level rollups whose markdown heading contains "disposition":
#      `## Round-3 disposition (...)`, `## Round-1 review disposition`
# Both alternatives are line-anchored and case-SENSITIVE: agent dispositions lead
# with an uppercase token or a `## ... disposition` heading, whereas human prose
# mentions the words mid-sentence and lower-case ("looks fixed to me", "can you
# confirm this is fixed?", "deferred material"). The old free-floating
# case-insensitive substring match hid those human comments entirely — the exact
# masking class this tool exists to prevent (PR #151 review, NPC-714).
#
# Two oniguruma/jq gotchas baked into this pattern (do not "simplify" away):
#  - `^` already matches at every line-start in oniguruma; NO `(?m)` flag is
#    needed (and `(?m)` there means dot-matches-newline, which would wrongly let
#    the heading alt's `.*` span lines). So the test() calls pass no flags.
#  - NO `\b`: the pattern is interpolated into a jq program string, and jq parses
#    `\b` as the JSON backspace escape (0x08) before oniguruma ever sees it — a
#    literal backspace that never matches. `[*_ ]*` absorbs leading emphasis
#    markers; the uppercase-at-line-start anchor is the boundary instead.
DISPOSITION_PATTERN='^([*_ ]*(FIXED|DECLINED|DEFERRED)|#{1,6} .*[Dd]isposition)'

# Now enable strict mode for the per-PR loop. Per-PR `gh` calls
# explicitly use `|| echo ""` + a guard so a transient failure on one
# PR degrades to "skip with warning" rather than killing the whole loop.
set -eu

for PR in "$@"; do
    echo "=== PR #$PR ==="

    STATE=$(gh pr view "$PR" --repo "$REPO" --json state --jq .state 2>/dev/null || echo "")
    if [ -z "$STATE" ]; then
        echo "  !! could not fetch PR #$PR (does it exist? auth blip? rate limit?)"
        echo ""
        continue
    fi
    MERGEABLE=$(gh pr view "$PR" --repo "$REPO" --json mergeable --jq .mergeable 2>/dev/null || echo "UNKNOWN")
    MERGE_STATUS=$(gh pr view "$PR" --repo "$REPO" --json mergeStateStatus --jq .mergeStateStatus 2>/dev/null || echo "UNKNOWN")
    echo "State: $STATE  Mergeable: $MERGEABLE  MergeStateStatus: $MERGE_STATUS"

    if [ "$STATE" = "MERGED" ]; then
        echo "  ** MERGED ** (nothing further to walk)"
        echo ""
        continue
    fi
    if [ "$MERGEABLE" = "CONFLICTING" ]; then
        echo "  !! MERGE CONFLICT — needs resolution"
    fi

    # --- Inline review comments (with disposition resolution) ---
    # Disposition logic assumes `in_reply_to_id` points to the THREAD ROOT,
    # not the immediate parent. This is correct for GitHub's pull-request
    # review-comments API today — the API flattens threaded replies, so
    # every reply at any depth has `in_reply_to_id` = root review-comment id.
    # If GitHub ever switches to nested-reply threading, replies at depth ≥ 2
    # would point to a non-root parent and the root would never get
    # dispositioned. Re-verify the assumption if disposition labels look wrong.
    #
    # AUTHOR-feedback exception (NPC-714 RCA): the agent posts dispositions AS
    # $AUTHOR, but a HUMAN reviewer sharing the same GitHub login also reviews
    # as $AUTHOR. Excluding all $AUTHOR comments would hide the human's own
    # review feedback (this masked user comments on 3 PRs before it was caught).
    # So exclude a $AUTHOR comment ONLY when its body matches the disposition
    # pattern (a genuine agent FIXED/DECLINED/DEFERRED note); SHOW $AUTHOR
    # comments that lack disposition language — those are human feedback.
    echo "--- Inline review comments (full history) ---"
    gh api --paginate "repos/$REPO/pulls/$PR/comments" \
        --jq "
            (.
              | map(select(.user.login == \"$AUTHOR\" and (.body | test(\"$DISPOSITION_PATTERN\"))))
              | map(.in_reply_to_id // empty)
              | unique) as \$dispositioned_ids
            |
            .[]
            | select(.in_reply_to_id == null)
            | select((.user.login != \"$AUTHOR\") or ((.body | test(\"$DISPOSITION_PATTERN\")) | not))
            | (if (.id as \$id | \$dispositioned_ids | index(\$id)) then \"[DISPOSITIONED]\" else \"[OPEN]    \" end) as \$status
            | \"\(\$status) \(.user.login) \(.path // \"?\"):\(.line // .original_line // 0)\\n  \(.body | gsub(\"\\r?\\n\"; \"\\n  \"))\\n---\"
        " 2>/dev/null

    # --- Top-level review comments ---
    echo "--- Top-level comments (full history) ---"
    gh pr view "$PR" --repo "$REPO" --comments --json comments \
        --jq "
            ([.comments[]
              | select(.author.login == \"$AUTHOR\" and (.body | test(\"$DISPOSITION_PATTERN\")))
              | .createdAt
             ] | max) as \$latest_author_dispo
            |
            .comments[]
            | select(.author.login != \"linear\")
            | select((.author.login != \"$AUTHOR\") or ((.body | test(\"$DISPOSITION_PATTERN\")) | not))
            | (if (\$latest_author_dispo != null and .createdAt < \$latest_author_dispo)
                  then \"[DISPOSITIONED-by-later-author-reply]\"
                  else \"[OPEN]                                 \" end) as \$status
            | \"\(\$status) \(.author.login) (\(.createdAt[:16]))\\n  \(.body | gsub(\"\\r?\\n\"; \"\\n  \"))\\n---\"
        " 2>/dev/null

    # --- Formal review submissions ---
    echo "--- Review submissions ---"
    gh pr view "$PR" --repo "$REPO" --json reviews \
        --jq '.reviews[] | select(.body != "") | .author.login + " (\(.state), \(.submittedAt[:16])):\n  " + (.body | gsub("\r?\n"; "\n  ")) + "\n---"' \
        2>/dev/null

    echo ""
done
