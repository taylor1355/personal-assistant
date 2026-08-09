"""Read-only GitHub PR attention scan across the user's active dev repos.

The bottleneck this attacks: the user runs several Claude Code orchestrators in
parallel (npc-simulation and friends), each producing PRs, review rounds, and
escalations across GitHub / Linear / chat. Knowing *which item needs a human
decision right now* requires bouncing between channels and reading long threads.
This module condenses the GitHub half into one attention-ordered report the
dev-briefing skill can deliver to a phone.

Design constraints (docs/DEV_ATTENTION.md):
- Read-only. Uses ``gh`` (the GitHub CLI) with the host's existing auth; only
  ever runs ``gh pr list`` queries. Merging stays a human act.
- Facts, not verdicts. A PR that is approved + green + conflict-free is
  reported as "looks merge-ready" with an explicit caveat — an automated
  reviewer's round may still be mid-flight, and only a completed round with
  zero findings makes a PR actually merge-ready.
- Degrades to a clear message (calendar_read's pattern) when ``gh`` is missing,
  unauthenticated, or ``PA_DEV_REPOS`` is unset. Never raises at the tool
  boundary.

Stdlib-only so the MCP server gains no dependency and tests run anywhere.
"""
from __future__ import annotations

import json
import os
import subprocess
from datetime import UTC, datetime
from typing import Any, Callable

# Comma-separated ``owner/repo`` list. No default: repos are user config, not
# code (architecture principle 9), and an empty value must read as "not
# configured", never as "no PRs anywhere".
DEV_REPOS_ENV = "PA_DEV_REPOS"

_PR_FIELDS = (
    "number,title,url,isDraft,mergeable,reviewDecision,statusCheckRollup,"
    "updatedAt,headRefName,author"
)

# gh's --limit ceiling for one repo's scan. A repo returning exactly this many
# rows may hold more; the report says so rather than silently under-reporting.
_PR_LIMIT = 30

# Attention buckets, most decision-worthy first. The report preserves this order.
BUCKET_ORDER = (
    "conflict",
    "ci-failing",
    "changes-requested",
    "looks-merge-ready",
    "awaiting-review",
    "draft",
)

_BUCKET_HEADINGS = {
    "conflict": "Merge conflict — needs a rebase routed to its owning session",
    "ci-failing": "CI failing — needs routing to whoever owns the branch",
    "changes-requested": "Changes requested — review round has open findings",
    "looks-merge-ready": (
        "Looks merge-ready (approved, checks green, no conflict) — verify the "
        "latest review round actually completed with zero findings before merging"
    ),
    "awaiting-review": "Open, no decision surfaced yet",
    "draft": "Draft — in progress, nothing for you",
}

Runner = Callable[..., subprocess.CompletedProcess]


def configured_repos(env: dict[str, str] | None = None) -> list[str]:
    """The ``owner/repo`` list from PA_DEV_REPOS, empty when unset."""
    source = env if env is not None else os.environ
    raw = source.get(DEV_REPOS_ENV, "")
    return [r.strip() for r in raw.split(",") if r.strip()]


def _ci_state(status_check_rollup: Any) -> str:
    """Collapse gh's statusCheckRollup list into failing / pending / green / none.

    Entries are CheckRun objects (``conclusion``/``status``) or StatusContext
    objects (``state``); both shapes appear in one list.
    """
    if not status_check_rollup:
        return "none"
    failing = {"FAILURE", "ERROR", "TIMED_OUT", "CANCELLED", "ACTION_REQUIRED"}
    saw_pending = False
    for check in status_check_rollup:
        verdict = (check.get("conclusion") or check.get("state") or "").upper()
        if verdict in failing:
            return "failing"
        if verdict in ("", "PENDING", "EXPECTED", "QUEUED", "IN_PROGRESS"):
            saw_pending = True
    return "pending" if saw_pending else "green"


def classify(pr: dict[str, Any]) -> str:
    """Attention bucket for one ``gh pr list`` JSON record."""
    if pr.get("isDraft"):
        return "draft"
    if pr.get("mergeable") == "CONFLICTING":
        return "conflict"
    ci = _ci_state(pr.get("statusCheckRollup"))
    if ci == "failing":
        return "ci-failing"
    decision = pr.get("reviewDecision") or ""
    if decision == "CHANGES_REQUESTED":
        return "changes-requested"
    if decision == "APPROVED" and ci in ("green", "none") and pr.get("mergeable") == "MERGEABLE":
        return "looks-merge-ready"
    return "awaiting-review"


def _age_days(updated_at: str, now: datetime) -> str:
    try:
        updated = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
    except ValueError:
        return ""
    days = max(0, (now - updated).days)
    return "today" if days == 0 else f"{days}d ago"


def _mergeability_note(pr: dict[str, Any]) -> str:
    """'' unless GitHub hasn't computed mergeability yet — in which case a
    conflict cannot be ruled out and the report must say so rather than let the
    PR sit under a bucket heading implying nothing is owed."""
    return "mergeability not yet computed" if pr.get("mergeable") == "UNKNOWN" else ""


def _format_pr(pr: dict[str, Any], repo: str, now: datetime) -> str:
    ci = _ci_state(pr.get("statusCheckRollup"))
    age = _age_days(pr.get("updatedAt", ""), now)
    author = (pr.get("author") or {}).get("login", "")
    details = ", ".join(x for x in (
        f"ci {ci}" if ci != "none" else "", _mergeability_note(pr), age, author,
    ) if x)
    suffix = f" ({details})" if details else ""
    return (
        f"- [{repo.split('/')[-1]}] #{pr['number']} {pr['title']}{suffix}\n"
        f"  {pr.get('url', '')}"
    )


def fetch_prs(repo: str, runner: Runner = subprocess.run) -> list[dict[str, Any]]:
    """Open PRs for one repo via ``gh``. Raises on any failure; the caller owns
    turning failures into controlled report text."""
    result = runner(
        ["gh", "pr", "list", "-R", repo, "--state", "open",
         "--json", _PR_FIELDS, "--limit", str(_PR_LIMIT)],
        capture_output=True, text=True, timeout=60,
    )
    if result.returncode != 0:
        raise RuntimeError(f"gh failed for {repo}: {(result.stderr or '').strip()[:300]}")
    return json.loads(result.stdout)


def build_report(
    repos: list[str],
    runner: Runner = subprocess.run,
    now: datetime | None = None,
) -> str:
    """Attention-ordered cross-repo PR report. Per-repo fetch failures are
    reported inline so one bad repo never hides the others."""
    if not repos:
        return (
            f"dev PR scan not configured: set {DEV_REPOS_ENV} to a comma-separated "
            "owner/repo list (e.g. 'taylor1355/npc-simulation,taylor1355/npc')"
        )
    now = now or datetime.now(UTC)
    buckets: dict[str, list[str]] = {b: [] for b in BUCKET_ORDER}
    errors: list[str] = []
    truncated: list[str] = []
    total = 0
    for repo in repos:
        try:
            prs = fetch_prs(repo, runner=runner)
        except FileNotFoundError:
            return "dev PR scan unavailable: the GitHub CLI ('gh') is not installed on this host"
        except (RuntimeError, OSError, json.JSONDecodeError, subprocess.SubprocessError) as e:
            errors.append(f"- {repo}: {e}")
            continue
        if len(prs) >= _PR_LIMIT:
            truncated.append(f"- {repo}: showing first {_PR_LIMIT} of possibly more open PRs")
        for pr in prs:
            total += 1
            buckets[classify(pr)].append(_format_pr(pr, repo, now))
    lines: list[str] = [f"Open PRs across {len(repos)} repo(s): {total}"]
    for bucket in BUCKET_ORDER:
        if not buckets[bucket]:
            continue
        lines.append(f"\n{_BUCKET_HEADINGS[bucket]}:")
        lines.extend(buckets[bucket])
    if truncated:
        lines.append("\nIncomplete scans (raise _PR_LIMIT or split the repo list):")
        lines.extend(truncated)
    if errors:
        lines.append("\nRepos that could not be scanned:")
        lines.extend(errors)
    if total == 0 and not errors:
        lines.append("No open PRs anywhere — nothing waiting on you.")
    return "\n".join(lines)
