#!/usr/bin/env python3
# Ported from npc-simulation tools/ for the /work skill. Internal NPC-xxx
# references are original provenance (they document why the code is shaped
# this way); they are npc-simulation issue ids, not personal-assistant ones.
"""PR cascade-impact shortlist — implementation.

Invoked by tools/check_pr_cascade.sh from the project root. Given a
just-merged PR number and a list of currently-open PR numbers (or
auto-discovered open PRs if none provided), reports which open PRs
likely have reviewer feedback now invalidated by the merge — either
because an inline comment was anchored to a file the merge rewrote
(HIGH-CONF) or because a review/issue comment body mentioned a path
that intersects the merge's file set (HEURISTIC).

Output: markdown by default, JSON with --json. Both forms enumerate
per-PR impacts; PRs with no intersection are omitted.

The tool is a shortlist generator — manual review remains the gate.
The heuristic body-regex will false-positive on comments that mention
paths in passing. This is acceptable per NPC-667's design: a shortlist
that catches false positives is cheaper than one that misses real
cascades.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from typing import Iterable

# ---------- Config ----------

# Body-regex for path extraction. Anchored on the project's top-level dirs
# to filter out arbitrary path-shaped strings. Optional extension boundary
# (e.g. `.gd`, `.md`, `.py`) helps but isn't required — `tools/foo` is a
# plausible bare reference too. Trailing punctuation (`)`, `]`, `"`, `'`,
# `,`, `.` at end of sentence) is excluded from the match.
FILE_PATH_RE = re.compile(
    # Body: zero or more permissive chars (excludes whitespace, brackets,
    # quotes, comma). Final char: same exclusions PLUS sentence-ending
    # punctuation (. ? ! : ;) so we don't capture trailing periods like
    # "see src/foo.gd." (gemini-flagged, PR #156 round 1).
    r"(?:src|test|tools|docs|\.github)/[^\s\)\]\"\',]*[^\s\)\]\"\',\.\?\!\:\;]"
)

# Per-gh-call fetch timeout (NOT per-PR). Each PR triggers 3 sequential gh
# calls (inline comments, reviews, issue comments), so worst-case latency
# per PR is ~3 × this value. With a 5-way ThreadPoolExecutor and typical
# 3–5 PR session, the dominant cost is the slowest PR's 3-call serial chain.
# Acceptance criterion is <5s wallclock for typical case (verified against
# PR #152 at 5.1s); pathological PRs (hundreds of inline comments + paginated
# review summaries) may exceed. Surface a per-PR warning on timeout and
# continue. Future work: thread a shared deadline through all three calls
# if the typical case starts trending toward the cap.
DEFAULT_PR_TIMEOUT_SECONDS = 5

# Parallelism cap. gh API calls are I/O-bound; 5 in flight is plenty for
# typical session sizes and stays well under the 5000/hr authenticated
# rate limit (5 PRs * 3 endpoints = 15 calls per invocation).
DEFAULT_MAX_WORKERS = 5

# ---------- Data classes ----------


@dataclass
class HighConfImpact:
    path: str
    comment_user: str
    comment_at: str


@dataclass
class HeuristicImpact:
    path: str
    source: str  # "review" | "issue_comment"
    source_user: str


@dataclass
class PRImpact:
    pr: int
    high_confidence: list[HighConfImpact] = field(default_factory=list)
    heuristic: list[HeuristicImpact] = field(default_factory=list)
    error: str | None = None

    @property
    def is_empty(self) -> bool:
        return not self.high_confidence and not self.heuristic and not self.error


# ---------- gh subprocess wrappers ----------


def _run_gh(args: list[str], timeout: float | None = None) -> str:
    """Run a gh command and return stdout. Raises on non-zero exit.

    Forces UTF-8 decoding: Python's text-mode default on Windows is cp1252,
    which fails on gh's UTF-8 output whenever a comment contains non-cp1252
    bytes (emoji, smart quotes, non-Latin script). Same flavor as the
    drift tool's Windows fix in PR #121.
    """
    try:
        result = subprocess.run(
            ["gh", *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError:
        raise RuntimeError(
            "gh CLI is not installed or not on PATH "
            "(install: https://cli.github.com/)"
        ) from None
    if result.returncode != 0:
        raise RuntimeError(
            f"gh {' '.join(args)} failed (rc={result.returncode}): "
            f"{result.stderr.strip()}"
        )
    return result.stdout


def get_repo() -> str:
    """Return owner/repo for the current gh-authed repository."""
    out = _run_gh(["repo", "view", "--json", "nameWithOwner", "-q", ".nameWithOwner"])
    repo = out.strip()
    if not repo:
        raise RuntimeError(
            "could not determine current repo. Run inside a gh-authed clone "
            "or pass --repo owner/name."
        )
    return repo


def get_open_prs(repo: str) -> list[int]:
    """Return numbers of currently-open PRs."""
    out = _run_gh(
        [
            "pr",
            "list",
            "--repo",
            repo,
            "--state",
            "open",
            "--json",
            "number",
            "--jq",
            ".[].number",
            "--limit",
            "100",
        ]
    )
    return [int(line) for line in out.splitlines() if line.strip()]


def get_merged_pr_files(repo: str, pr: int, timeout: float) -> set[str]:
    """Return the set of file paths the merged PR touched."""
    out = _run_gh(
        [
            "api",
            f"repos/{repo}/pulls/{pr}/files",
            "--paginate",
            "--jq",
            ".[].filename",
        ],
        timeout=timeout,
    )
    return {line.strip() for line in out.splitlines() if line.strip()}


def get_pr_inline_comments(repo: str, pr: int, timeout: float) -> list[dict]:
    """Return inline review comments (those anchored to a file/line)."""
    out = _run_gh(
        [
            "api",
            f"repos/{repo}/pulls/{pr}/comments",
            "--paginate",
            "--jq",
            "[.[] | {path: .path, user: .user.login, created_at: .created_at}]",
        ],
        timeout=timeout,
    )
    # gh --paginate emits one JSON array per page back-to-back; the parser
    # walks that concatenation. See _parse_concatenated_json_arrays.
    return _parse_concatenated_json_arrays(out)


def get_pr_reviews(repo: str, pr: int, timeout: float) -> list[dict]:
    """Return review summaries (with body text — may contain path mentions)."""
    out = _run_gh(
        [
            "api",
            f"repos/{repo}/pulls/{pr}/reviews",
            "--paginate",
            "--jq",
            "[.[] | {body: .body, user: .user.login, submitted_at: .submitted_at}]",
        ],
        timeout=timeout,
    )
    return _parse_concatenated_json_arrays(out)


def get_pr_issue_comments(repo: str, pr: int, timeout: float) -> list[dict]:
    """Return issue-level comments (non-review prose on the PR conversation)."""
    out = _run_gh(
        [
            "api",
            f"repos/{repo}/issues/{pr}/comments",
            "--paginate",
            "--jq",
            "[.[] | {body: .body, user: .user.login, created_at: .created_at}]",
        ],
        timeout=timeout,
    )
    return _parse_concatenated_json_arrays(out)


def _parse_concatenated_json_arrays(raw: str | None) -> list[dict]:
    """gh --paginate with --jq '[...]' emits one array per page back-to-back.

    The pages aren't separated by newlines reliably; they're concatenated as
    `][` joins. This helper splits on those joins and reparses, falling back
    to a JSONDecoder.raw_decode walk if the simple split fails.

    Defensively accepts None (which can happen if subprocess's reader thread
    crashes mid-decode) and treats it as empty.
    """
    if raw is None:
        return []
    raw = raw.strip()
    if not raw:
        return []

    # Common case: single page, valid JSON array.
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass

    # Multi-page case: walk with raw_decode.
    decoder = json.JSONDecoder()
    pos = 0
    combined: list[dict] = []
    raw_stripped = raw
    while pos < len(raw_stripped):
        # Skip whitespace between arrays.
        while pos < len(raw_stripped) and raw_stripped[pos].isspace():
            pos += 1
        if pos >= len(raw_stripped):
            break
        try:
            obj, end = decoder.raw_decode(raw_stripped, pos)
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                f"could not parse gh output as concatenated JSON arrays "
                f"at offset {pos}: {exc}"
            )
        if isinstance(obj, list):
            combined.extend(obj)
        else:
            combined.append(obj)
        pos = end
    return combined


# ---------- Analysis ----------


# Strip line-number suffix (`:42`, `:42-50`) so `tools/foo.py:71` intersects
# with `tools/foo.py` in the merged-file set. CLAUDE.md actively encourages
# `file:line` citations and reviewers use them constantly; without this
# normalization the cascade tool misses its most common citation form.
LINE_SUFFIX_RE = re.compile(r":\d+(?:-\d+)?$")


def extract_paths_from_body(body: str | None) -> set[str]:
    """Find filesystem-path-shaped substrings in a comment body.

    Trailing line-number suffixes (`:42`, `:42-50`) are stripped before
    returning so the result intersects with the bare-path entries in the
    merged-file set.
    """
    if not body:
        return set()
    return {LINE_SUFFIX_RE.sub("", p) for p in FILE_PATH_RE.findall(body)}


def analyze_pr(
    repo: str,
    merged_files: set[str],
    pr: int,
    timeout: float,
) -> PRImpact:
    """Analyze a single open PR against the merged-file set."""
    impact = PRImpact(pr=pr)
    try:
        inline = get_pr_inline_comments(repo, pr, timeout)
        reviews = get_pr_reviews(repo, pr, timeout)
        issue_comments = get_pr_issue_comments(repo, pr, timeout)
    except subprocess.TimeoutExpired:
        impact.error = f"timeout after {timeout}s"
        return impact
    except RuntimeError as exc:
        impact.error = str(exc)
        return impact

    # HIGH-CONF: inline comments whose .path is in the merged file set.
    for c in inline:
        path = c.get("path")
        if path and path in merged_files:
            impact.high_confidence.append(
                HighConfImpact(
                    path=path,
                    comment_user=c.get("user") or "unknown",
                    comment_at=c.get("created_at") or "",
                )
            )

    # HEURISTIC: body-regex over reviews and issue comments, intersected with
    # merged_files. Dedupe by (path, source, source_user) to avoid double-counting
    # when the same reviewer's summary lists the same path twice.
    seen: set[tuple[str, str, str]] = set()
    for review in reviews:
        body_paths = extract_paths_from_body(review.get("body"))
        for path in body_paths & merged_files:
            user = review.get("user") or "unknown"
            key = (path, "review", user)
            if key not in seen:
                seen.add(key)
                impact.heuristic.append(
                    HeuristicImpact(path=path, source="review", source_user=user)
                )
    for ic in issue_comments:
        body_paths = extract_paths_from_body(ic.get("body"))
        for path in body_paths & merged_files:
            user = ic.get("user") or "unknown"
            key = (path, "issue_comment", user)
            if key not in seen:
                seen.add(key)
                impact.heuristic.append(
                    HeuristicImpact(
                        path=path, source="issue_comment", source_user=user
                    )
                )

    return impact


def analyze_all(
    repo: str,
    merged_files: set[str],
    open_prs: Iterable[int],
    timeout: float,
    max_workers: int,
) -> list[PRImpact]:
    """Fan out per-PR analysis in a thread pool. Returns one PRImpact per PR."""
    open_prs = list(open_prs)
    results: dict[int, PRImpact] = {}
    with concurrent.futures.ThreadPoolExecutor(
        max_workers=min(max_workers, max(1, len(open_prs)))
    ) as pool:
        future_to_pr = {
            pool.submit(analyze_pr, repo, merged_files, pr, timeout): pr
            for pr in open_prs
        }
        for future in concurrent.futures.as_completed(future_to_pr):
            pr = future_to_pr[future]
            try:
                results[pr] = future.result()
            except Exception as exc:  # noqa: BLE001 — pool wrapper
                impact = PRImpact(pr=pr)
                impact.error = f"unexpected error: {exc}"
                results[pr] = impact
    return [results[pr] for pr in open_prs]


# ---------- Rendering ----------


def render_markdown(merged_pr: int, impacts: list[PRImpact]) -> str:
    """Human-readable markdown report. Empty-impact PRs are omitted."""
    non_empty = [i for i in impacts if not i.is_empty]
    if not non_empty:
        return f"No cross-PR impacts found for merge of #{merged_pr}.\n"

    lines: list[str] = []
    for impact in non_empty:
        if impact.error:
            lines.append(
                f"PR #{impact.pr} — could not analyze: {impact.error}"
            )
            lines.append("")
            continue
        lines.append(
            f"PR #{impact.pr} — likely impacted by merge of #{merged_pr}:"
        )
        if impact.high_confidence:
            lines.append("  HIGH-CONF (inline comment):")
            for h in impact.high_confidence:
                user = h.comment_user
                when = h.comment_at[:10] if h.comment_at else "unknown"
                lines.append(f"    {h.path}  ← comment by {user} @ {when}")
        if impact.heuristic:
            lines.append("  HEURISTIC (body match):")
            for h in impact.heuristic:
                source_label = (
                    "review summary"
                    if h.source == "review"
                    else "issue comment"
                )
                lines.append(
                    f"    {h.path}  ← mentioned in {h.source_user} {source_label}"
                )
        lines.append("")
    return "\n".join(lines)


def render_json(merged_pr: int, checked: list[int], impacts: list[PRImpact]) -> str:
    """Machine-readable JSON. Includes PRs with no impacts for completeness."""
    payload = {
        "merged_pr": merged_pr,
        "checked_prs": checked,
        "impacts": [
            {
                "pr": impact.pr,
                "error": impact.error,
                "high_confidence": [
                    {
                        "path": h.path,
                        "comment_user": h.comment_user,
                        "comment_at": h.comment_at,
                    }
                    for h in impact.high_confidence
                ],
                "heuristic": [
                    {
                        "path": h.path,
                        "source": h.source,
                        "source_user": h.source_user,
                    }
                    for h in impact.heuristic
                ],
            }
            for impact in impacts
            # Include even empty-impact PRs per the docstring promise of
            # "for completeness". Downstream consumers (e.g., automation
            # that asserts "we DID check PR N and found nothing") need to
            # see them. Markdown rendering still filters for human brevity.
        ],
    }
    return json.dumps(payload, indent=2) + "\n"


# ---------- CLI ----------


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="check_pr_cascade.sh",
        description=(
            "Shortlist open PRs whose reviewer feedback may be invalidated "
            "by a just-merged PR."
        ),
    )
    parser.add_argument(
        "merged_pr",
        type=int,
        help="Number of the PR that just merged.",
    )
    parser.add_argument(
        "open_prs",
        type=int,
        nargs="*",
        help=(
            "Optional list of open PR numbers to check. If omitted, "
            "discovers all currently-open PRs via `gh pr list`."
        ),
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit JSON to stdout instead of markdown.",
    )
    parser.add_argument(
        "--repo",
        default=None,
        help="owner/name override (defaults to current gh-authed repo).",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_PR_TIMEOUT_SECONDS,
        help=(
            f"Per-PR gh-fetch timeout in seconds "
            f"(default: {DEFAULT_PR_TIMEOUT_SECONDS})."
        ),
    )
    parser.add_argument(
        "--max-workers",
        type=int,
        default=DEFAULT_MAX_WORKERS,
        help=(
            f"Max parallel gh fetches (default: {DEFAULT_MAX_WORKERS})."
        ),
    )
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)

    try:
        repo = args.repo or get_repo()
    except RuntimeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    # Resolve merged-PR file set first — if this fails (PR doesn't exist,
    # not merged, auth bad), bail before fanning out.
    try:
        merged_files = get_merged_pr_files(repo, args.merged_pr, args.timeout)
    except RuntimeError as exc:
        print(
            f"Error: could not fetch files for PR #{args.merged_pr}: {exc}",
            file=sys.stderr,
        )
        return 2
    except subprocess.TimeoutExpired:
        print(
            f"Error: timeout fetching files for PR #{args.merged_pr} "
            f"(after {args.timeout}s).",
            file=sys.stderr,
        )
        return 2

    if not merged_files:
        # Empty file set is unusual but not fatal — PR may have been pure-meta.
        print(
            f"Note: merged PR #{args.merged_pr} touched no files; "
            "no cascade analysis possible.",
            file=sys.stderr,
        )
        if args.json:
            print(render_json(args.merged_pr, [], []))
        else:
            print(f"No files in merged PR #{args.merged_pr}.")
        return 0

    # Resolve open-PR set.
    if args.open_prs:
        open_prs = [pr for pr in args.open_prs if pr != args.merged_pr]
    else:
        try:
            discovered = get_open_prs(repo)
        except RuntimeError as exc:
            print(f"Error: could not list open PRs: {exc}", file=sys.stderr)
            return 1
        open_prs = [pr for pr in discovered if pr != args.merged_pr]

    if not open_prs:
        if args.json:
            print(render_json(args.merged_pr, [], []))
        else:
            print(f"No open PRs to check against #{args.merged_pr}.")
        return 0

    impacts = analyze_all(
        repo=repo,
        merged_files=merged_files,
        open_prs=open_prs,
        timeout=args.timeout,
        max_workers=args.max_workers,
    )

    if args.json:
        sys.stdout.write(render_json(args.merged_pr, open_prs, impacts))
    else:
        sys.stdout.write(render_markdown(args.merged_pr, impacts))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
