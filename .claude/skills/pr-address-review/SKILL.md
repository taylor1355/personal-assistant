---
name: pr-address-review
description: Handle PR review feedback — gather, triage, fix, and push. Use after auto-reviewers post comments or when the user relays feedback.
argument-hint: "<PR number> [user context]"
disable-model-invocation: true
---

# PR Address Review

Handle review feedback on a PR you authored or are responsible for. Gather all comments, triage by severity, fix systematically, and push.

**Invoked as `/pr-address-review <number>`.** Parse any text after the PR number as user context (e.g., "5 ignore the formatting nits from Gemini"). This affects triage decisions in Step 2.

## Step 1: Gather All Feedback

Collect feedback from **all** sources using `--jq` for reliable cross-platform parsing.

```bash
REPO=$(gh repo view --json nameWithOwner -q .nameWithOwner)

# Top-level comments (excludes Linear linkback bot)
gh pr view $PR_NUMBER --comments --json comments \
  --jq '.comments[] | select(.author.login != "linear") |
    .author.login + " (" + .createdAt[:16] + "):\n" + .body[:3000] + "\n---"'

# Inline review comments (file-level feedback with line numbers)
gh api repos/$REPO/pulls/$PR_NUMBER/comments \
  --jq '.[] | .user.login + " " + (.path // "?") + ":" +
    ((.line // .original_line // 0) | tostring) + "\n" + .body[:600] + "\n---"'

# Review-level decisions (REQUEST_CHANGES, APPROVED)
gh pr view $PR_NUMBER --json reviews \
  --jq '.reviews[] | .author.login + " (" + .state + "): " + (.body[:500] // "")'
```

**Timestamp filtering**: After a push, only process comments newer than the push. Add `select(.createdAt > "YYYY-MM-DDTHH:MM:SSZ")` to skip previously-addressed feedback.

Present a summary table:

```
| # | Source | File:Line | Category | Summary |
|---|--------|-----------|----------|---------|
| 1 | claude | agent/src/.../intake_agent.py:127 | bug | linear_issue branch swallows non-RuntimeError exceptions |
| 2 | gemini | docs/ARCHITECTURE.md:84 | nit | "Cancelled" vs "Canceled" |
```

## Step 2: Triage by Severity

Sort all unresolved feedback into priority tiers:

1. **Correctness** — Bugs, logic errors, data corruption, crashes, proposal-queue bypass. Fix first.
2. **Architectural** — Trust-boundary violations, missing schema validation, cross-language contract drift. May be deferred with ADR + tech-debt issue if scope-expanding.
3. **Behavioral** — Side effects, unintended mutations, missing validation, edge cases.
4. **Style/Nits** — Naming, formatting, comment wording. Fix last — but **do fix them**. Nits are real feedback; ignoring them makes reviewers' jobs harder and can hide real issues (e.g., unnecessary guard clauses masking missing invariants).
5. **False positives** — Verify with tooling before dismissing.

**"Code or Doc?" checkpoint** — for each item:
- Read the actual code path before deciding. A suggestion to "update the docstring" may actually need a code fix.
- State: "Fix type: code-only / doc-only / both" with a one-line justification.
- Doc-only justification must include evidence (e.g., "behavior correct per test X, only comment is stale").

**For false-positive candidates**: Verify with tooling first — ruff, mypy, the test in question. Never dismiss on intuition alone.

**Apply user context**: If the user said to deprioritize a reviewer or skip categories, note which items are affected.

Present the triage plan and **wait for user approval** before proceeding.

## Step 3: Pattern Audit

**Before fixing anything**, spawn the **`pattern-auditor` agent** for each correctness and architectural item:
1. Describe the pattern and provide the example location
2. The agent classifies instances (violation vs exception) and assesses scope (isolated vs systemic)
3. If systemic, it recommends whether to fix in this PR or defer

For architectural items (tier 2):
1. Search Linear (`bash tools/linear search <topic>`) for matching tech-debt issues
2. If non-trivial and would expand PR scope: file a Linear issue (`tools/linear create ...`), reference in PR comment as deferral, link as a blocker if it gates other work
3. If small (< 30 lines, contained): just do it

## Step 4: Execute Fixes

Work through tiers in order: correctness → architectural → behavioral → style.

**For each fix:**
1. Make the code/doc change (per Step 2 determination)
2. If pattern audit found multiple instances, fix ALL of them
3. If the pattern represents a new anti-pattern, add it to `CLAUDE.md`'s anti-pattern table or `.claude/rules/architecture.md`'s table
4. If the fix reveals missing infrastructure, consider adding it (or filing an issue)
5. **Regression test decision** — explicitly state yes/no and why:
   - **Yes** if: subtle bug that could be reintroduced by refactoring, OR establishes a structural invariant, OR fixes a closed-schema gap
   - **No** if: covered by existing tests once wired, OR one-liner caught by any consumer test, OR doc/comment-only
6. Write the regression test if warranted

**After ALL fixes in a tier**: Spawn the **`code-quality` agent** in `verify` mode. Static analysis AND tests must pass before moving to the next tier.

## Step 5: Draft Responses

For each addressed item, draft a reply comment:
- **Correctness fixes**: What was wrong, what was fixed, whether the pattern existed elsewhere, regression tests added
- **Systemic fixes**: List ALL locations changed, not just the one flagged
- **Deferred items**: Deferral rationale, link to Linear issue tracking it
- **False positives**: Evidence (tooling output, spec reference, test proof)

Present all draft replies to the user. **Do not post replies without user approval.**

## Step 6: Extract Learnings

Check whether any feedback item reveals:

1. A missing anti-pattern rule for `CLAUDE.md` or `.claude/rules/architecture.md`?
2. A stale or insufficient rule in `.claude/rules/development-patterns.md` or `testing.md`?
3. A documentation gap that caused reviewer confusion (`docs/ARCHITECTURE.md`, `docs/PROPOSAL_FORMAT.md`, etc.)?
4. A tooling opportunity (a custom check that would have caught this)?
5. A skill that should be updated (`audit`, `pr`, `pr-review`, etc.)?

For each finding, propose the specific change (exact text, target file). Present proposals — do not apply without approval.

## Step 7: Commit and Push

**IMPORTANT: Batch all fixes into a single commit+push.** Each push triggers auto-reviewers (Claude, Gemini), so multiple small pushes create noise and duplicate review cycles.

1. **Ask user for commit approval.** Present staged changes, proposed commit message, and regression-test decision log.
2. After approval, commit and push once.
3. **Post-push verification**: Run static analysis + tests one final time on the pushed commit.
4. Report: changes pushed, items addressed, items deferred with tracking references.

## Step 8: Post-Push Review Loop

**You own this loop. Do not wait for the user to tell you to check for feedback.** If the harness supports `CronCreate` or an equivalent scheduling tool, set up a poll:

```
CronCreate(cron: "*/3 * * * *", recurring: true,
  prompt: "Check PR <N> for new comments since the last push.
           If merged → mark linked Linear issues Done via tools/linear done <PA-NN>.
           If conflicts → flag immediately.
           If new feedback (including nits) → summarize and present fix plan.
           After 3 empty checks → cancel this cron job.")
```

If `CronCreate` is unavailable, prompt the user to ping you when feedback arrives or after the merge.

On each poll:
1. **Merged**: Mark issues Done via Linear, note to user.
2. **Merge conflicts**: Flag immediately.
3. **New feedback**: Triage and present fix plan. Go back to Step 2.
4. **3 empty checks**: Cancel cron, wait for user.

---

## Behavioral Rules

### Severity Over Order
Always triage first. A correctness bug at comment #6 takes priority over a style nit at comment #1.

### Code Over Docs
When a reviewer suggests "just update the comment/docstring," read the code path first. The reviewer's suggestion is a hint, not a prescription.

### Audit Before Declaring Isolated
Never say "this is an isolated case" without searching.

### Tooling Over Intuition
Verify false-positive candidates with tooling (ruff, mypy, tests), not pattern recognition.

### Scope Discipline for Architectural Items
Large architectural fixes (changing trust boundaries, restructuring proposal flow, cross-language contract changes) should be deferred to a dedicated PR with a Linear issue tracking them. The feedback-handling commit should fix bugs, not redesign systems.

### Every Review Improves the Process
If a reviewer caught something `CLAUDE.md` or `.claude/rules/` should have prevented, that's a gap. Step 6 exists to close it.

### Systemic Fix Decision Procedure
Before fixing any issue:
1. Does this pattern exist in other files? → Fix all instances
2. Is this tracked in Linear? → Search; if found, do the proper fix and link
3. Could this be prevented by a project-level convention? → Add to `CLAUDE.md` or rules
4. Is this a known bug? → Search Linear; update or create issue

### Test Integrity
- Never delete tests to make the suite pass
- Never loosen assertions as a fix
- Never suppress lint warnings without fixing the underlying issue
- Never write trivial tests for coverage padding (the 90% branch-coverage gate is real but tests must have regression value, per `.claude/rules/testing.md`)
