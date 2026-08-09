"""Tests for the dev-attention PR scan (stdlib only; no gh, no network).

Run from the repo root:
    python -m unittest discover -s pa_mcp/tests
"""
from __future__ import annotations

import json
import sys
import unittest
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import dev_attention  # noqa: E402

NOW = datetime(2026, 8, 9, 12, 0, tzinfo=UTC)


def pr(
    number: int = 1,
    title: str = "a change",
    is_draft: bool = False,
    mergeable: str = "MERGEABLE",
    review_decision: str = "",
    checks: list | None = None,
    updated_at: str = "2026-08-08T12:00:00Z",
) -> dict:
    return {
        "number": number,
        "title": title,
        "url": f"https://github.com/o/r/pull/{number}",
        "isDraft": is_draft,
        "mergeable": mergeable,
        "reviewDecision": review_decision,
        "statusCheckRollup": checks or [],
        "updatedAt": updated_at,
        "headRefName": "feature/x",
        "author": {"login": "taylor1355"},
    }


def fake_runner(payloads: dict[str, list | Exception]):
    """A subprocess.run stand-in keyed by the -R repo argument."""

    def run(cmd, **_kwargs):
        repo = cmd[cmd.index("-R") + 1]
        payload = payloads[repo]
        if isinstance(payload, Exception):
            raise payload
        return SimpleNamespace(returncode=0, stdout=json.dumps(payload), stderr="")

    return run


class ConfiguredReposTest(unittest.TestCase):
    def test_unset_is_empty(self):
        self.assertEqual(dev_attention.configured_repos(env={}), [])

    def test_parses_and_strips(self):
        env = {dev_attention.DEV_REPOS_ENV: " a/b , c/d ,,"}
        self.assertEqual(dev_attention.configured_repos(env=env), ["a/b", "c/d"])


class ClassifyTest(unittest.TestCase):
    def test_draft_wins_over_everything(self):
        p = pr(is_draft=True, mergeable="CONFLICTING", review_decision="APPROVED")
        self.assertEqual(dev_attention.classify(p), "draft")

    def test_conflict(self):
        self.assertEqual(dev_attention.classify(pr(mergeable="CONFLICTING")), "conflict")

    def test_ci_failing(self):
        p = pr(checks=[{"conclusion": "SUCCESS"}, {"conclusion": "FAILURE"}])
        self.assertEqual(dev_attention.classify(p), "ci-failing")

    def test_changes_requested(self):
        p = pr(review_decision="CHANGES_REQUESTED")
        self.assertEqual(dev_attention.classify(p), "changes-requested")

    def test_looks_merge_ready_requires_green_and_mergeable(self):
        ready = pr(review_decision="APPROVED", checks=[{"conclusion": "SUCCESS"}])
        self.assertEqual(dev_attention.classify(ready), "looks-merge-ready")
        # approved but CI still running is NOT merge-ready
        pending = pr(review_decision="APPROVED", checks=[{"status": "IN_PROGRESS", "conclusion": ""}])
        self.assertEqual(dev_attention.classify(pending), "awaiting-review")
        # approved but mergeability unknown is NOT merge-ready
        unknown = pr(review_decision="APPROVED", mergeable="UNKNOWN")
        self.assertEqual(dev_attention.classify(unknown), "awaiting-review")

    def test_no_reviews_awaits_review(self):
        self.assertEqual(dev_attention.classify(pr()), "awaiting-review")

    def test_status_context_shape_counts_too(self):
        # StatusContext entries carry `state`, not `conclusion`
        p = pr(checks=[{"state": "ERROR"}])
        self.assertEqual(dev_attention.classify(p), "ci-failing")


class BuildReportTest(unittest.TestCase):
    def test_unconfigured_names_the_env_var(self):
        report = dev_attention.build_report([])
        self.assertIn("not configured", report)
        self.assertIn(dev_attention.DEV_REPOS_ENV, report)

    def test_groups_by_bucket_most_urgent_first(self):
        runner = fake_runner({
            "o/game": [
                pr(number=10, title="rebase me", mergeable="CONFLICTING"),
                pr(number=11, title="review me"),
            ],
            "o/assistant": [
                pr(number=3, title="ship me", review_decision="APPROVED",
                   checks=[{"conclusion": "SUCCESS"}]),
            ],
        })
        report = dev_attention.build_report(["o/game", "o/assistant"], runner=runner, now=NOW)
        self.assertIn("Open PRs across 2 repo(s): 3", report)
        # conflict section precedes merge-ready, which precedes awaiting-review
        self.assertLess(report.index("#10"), report.index("#3"))
        self.assertLess(report.index("#3"), report.index("#11"))
        self.assertIn("verify the latest review round", report)
        self.assertIn("[game]", report)

    def test_one_bad_repo_does_not_hide_the_others(self):
        runner = fake_runner({
            "o/good": [pr(number=1)],
            "o/bad": RuntimeError("gh failed for o/bad: auth"),
        })
        report = dev_attention.build_report(["o/good", "o/bad"], runner=runner, now=NOW)
        self.assertIn("#1", report)
        self.assertIn("could not be scanned", report)
        self.assertIn("o/bad", report)

    def test_missing_gh_degrades_to_message(self):
        runner = fake_runner({"o/r": FileNotFoundError("gh")})
        report = dev_attention.build_report(["o/r"], runner=runner, now=NOW)
        self.assertIn("gh", report)
        self.assertIn("not installed", report)

    def test_no_open_prs_says_so(self):
        runner = fake_runner({"o/r": []})
        report = dev_attention.build_report(["o/r"], runner=runner, now=NOW)
        self.assertIn("nothing waiting on you", report)

    def test_unknown_mergeability_is_never_silent(self):
        # GitHub computes mergeability lazily: a just-pushed PR reports UNKNOWN
        # and could actually be conflicting. It must carry a caveat in its line,
        # not sit under a bucket as if nothing were owed.
        runner = fake_runner({"o/r": [pr(number=7, mergeable="UNKNOWN")]})
        report = dev_attention.build_report(["o/r"], runner=runner, now=NOW)
        self.assertIn("mergeability not yet computed", report)

    def test_malformed_record_degrades_instead_of_raising(self):
        # The tool boundary promises "never raises": a gh record missing
        # number/title, with updatedAt null, must still land in the report.
        runner = fake_runner({"o/r": [{"mergeable": "MERGEABLE", "updatedAt": None}]})
        report = dev_attention.build_report(["o/r"], runner=runner, now=NOW)
        self.assertIn("#?", report)
        self.assertIn("(untitled)", report)

    def test_full_page_notes_possible_truncation(self):
        page = [pr(number=n) for n in range(dev_attention.PR_LIMIT)]
        report = dev_attention.build_report(
            ["o/full", "o/small"],
            runner=fake_runner({"o/full": page, "o/small": [pr(number=99)]}),
            now=NOW,
        )
        self.assertIn("Incomplete scans", report)
        self.assertIn("o/full", report)
        self.assertNotIn("o/small: showing first", report)


if __name__ == "__main__":
    unittest.main()
