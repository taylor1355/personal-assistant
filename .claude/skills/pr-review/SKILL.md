---
name: pr-review
description: In-depth PR review — reads diff, runs static analysis and tests, checks architecture compliance, and provides detailed feedback. More thorough than auto-reviewers.
argument-hint: "<PR number or branch name>"
disable-model-invocation: true
---

# PR Review

Perform a thorough code review of a PR. This goes deeper than the automated Claude/Gemini reviewers: read every changed file in full context, run static analysis and tests locally, check architecture compliance, and produce actionable feedback.

**Invoked as `/pr-review <number>`.** The argument can be a PR number or branch name.

## Step 1: Gather Context

```bash
# Get the diff
gh pr diff $PR_NUMBER

# Get PR description and metadata
gh pr view $PR_NUMBER

# Get the commit history
gh pr view $PR_NUMBER --json commits --jq '.commits[].messageHeadline'

# Check current review status
gh pr view $PR_NUMBER --json reviews --jq '.reviews[] | .author.login + ": " + .state'
```

Read the PR description to understand intent. Read the linked Linear issue(s) if referenced (`PA-NN`).

## Step 2: Read Changed Files in Full Context

For every file in the diff:
1. **Read the full file**, not just the changed lines. Changes make sense only in context.
2. Note what the file does, what subsystem it belongs to (`agent` / `executor` / `sync` / `dispatcher` / `sms` / `devops` / `tools/linear-pm` / `docs`), and how it connects to other systems.
3. For each change, understand *why* — does the commit message explain it? Does the PR description?

Build a mental model of the change as a whole before evaluating individual lines.

## Step 3: Architecture & Convention Compliance

Check the diff against project standards:

**Critical anti-patterns from CLAUDE.md (treat any of these as automatic blocking findings):**
- **Proposal-queue bypass** — agent code writing to the vault, calendar, email, GitHub, or any user state directly. The only write paths from the agent container are `proposal_enqueue` and `LinearClient` (for auto-applied Linear ops).
- **Unvalidated executor input** — executor code applying a proposal without running the schema validator first.
- **Hardcoded user state** — vault paths, OAuth tokens, phone numbers, API keys in source. All must come from `config/*.yaml` or `.env`.
- **Write credentials in the container** — any Dockerfile/compose layer that puts write-scoped credentials inside the agent container.
- **Cross-system writes outside `00 - Assistant/`** — direct vault writes to user content without a user-approved proposal.

**Other anti-patterns from `.claude/rules/architecture.md`:**
- Poll loops in agent code (`while True:` instead of event-driven wakes)
- Silent `if not x: return` at process boundaries (must log + early return)
- Mutable default args (`def f(xs=[])`)
- Mocking the proposal-queue invariant in tests
- Going around `LinearClient` with raw subprocess calls
- Bare `except:` / broad `except Exception:` swallowing
- Magic strings for action types / Linear states / labels (must use enums/constants/string-literal unions)
- Cross-language contracts as undocumented dicts (Pydantic ↔ Go struct ↔ TS type must mirror)

**From `.claude/rules/development-patterns.md`:**
- Proper logging (Python `logging.getLogger(__name__)`, Go `log/slog`) — not `print` / `log.Printf`
- Errors as concrete exception subclasses (not generic `Exception`)
- Pydantic `extra="forbid", frozen=True` on models crossing boundaries
- Subprocess: `check=False` + manual returncode check + domain exception with cmd+stdout+stderr

**From `.claude/rules/testing.md`:**
- Tests have regression value (would fail if behavior changes)
- No tautological assertions
- Mock at process boundaries, not inside our own code
- Don't mock the proposal-queue invariant
- Closed-schema tests on Pydantic models with `extra="forbid"`
- 90% branch coverage on the unit layer

## Step 4: Run Static Analysis

```bash
uv run --project agent ruff check agent
uv run --project agent mypy agent/src
cd executor && go vet ./... && cd ..
cd sync && go vet ./... && cd ..
```

Note any new warnings or errors introduced by this PR (compare against known pre-existing issues).

## Step 5: Run Tests

```bash
# Full Python suite
uv run --project agent pytest agent/tests 2>&1 | tee /tmp/review_tests.txt | tail -30

# Branch coverage on the unit layer
uv run --project agent pytest agent/tests --cov=agent/src --cov-branch --cov-report=term-missing

# Go services (when present)
cd executor && go test ./... -count=1 && cd ..
cd sync && go test ./... -count=1 && cd ..

# Find failures
grep -E "FAIL|ERROR" /tmp/review_tests.txt
```

Distinguish between:
- **New failures** caused by this PR → blocking
- **Pre-existing failures** → note but don't block (file a Linear issue if not tracked)

## Step 6: Evaluate

For each issue found, classify:

1. **Correctness** — Bugs, logic errors, crashes. Must fix before merge.
2. **Architectural** — Trust-boundary violations, proposal-queue bypass, cross-language contract drift. The five critical anti-patterns are automatic blockers.
3. **Behavioral** — Side effects, missing validation, edge cases. Should fix.
4. **Style/Nits** — Naming, formatting, readability. Nice to fix.
5. **Questions** — Things that aren't clearly wrong but need explanation.

For each item, provide:
- **Location**: `file:line`
- **What**: What the issue is
- **Why it matters**: What could go wrong / what convention it violates
- **Suggested fix**: Concrete suggestion, not "fix this"

### Positive feedback
Also note what's done well — good patterns, clean abstractions, thorough tests. Reviews that only list problems are demoralizing and miss the chance to reinforce good practices.

## Step 7: Check for Gaps

Things auto-reviewers often miss:

- **Missing tests** for new code paths — does every new public function have unit coverage? Are error paths tested?
- **Coverage shape** — has the diff dropped overall branch coverage below 90% on the unit layer?
- **Cross-language contract drift** — if the proposal schema changed, does the Go executor's mirror match? Did `docs/PROPOSAL_FORMAT.md` get updated?
- **Missing docs** for new public APIs — exported Python functions, exported Go symbols, new action types
- **Config-key drift** — new env var or YAML key without corresponding update in `.env.example` / `config/*.yaml.example`?
- **Cross-system effects** — does this change affect systems not in the diff? Check callers of modified functions.
- **Performance** — new per-wake work in hot paths? New unbounded subprocess calls?

## Step 8: Present Review

Structure the review as:

### Summary
2-3 sentences: what this PR does, whether it's ready to merge, and the overall quality assessment.

### Blocking Issues
Items that must be fixed before merge. Each with location, description, and suggested fix.

### Non-Blocking Issues
Items that should be fixed but aren't merge-blockers. Categorized by severity.

### Questions
Things that aren't clearly wrong but need clarification.

### What's Good
Patterns worth reinforcing.

### Test & Analysis Results
- Static analysis (ruff / mypy / go vet): PASS/FAIL (new issues only)
- Tests: PASS/FAIL with counts (new failures only)
- Branch coverage on the unit layer: percentage, deltas

### Verdict
One of:
- **Approve** — Ready to merge as-is
- **Approve with nits** — Merge after addressing minor items
- **Request changes** — Blocking issues must be resolved
- **Needs discussion** — Architectural questions that need alignment before proceeding

---

## Behavioral Rules

### Be Specific
"This could be improved" is useless. "Line 42: `foo` should use `bar` because [reason], like the pattern at `baz.py:99`" is actionable.

### Steelman the Author
Assume the author had reasons for their choices. If something looks wrong, consider whether you're missing context before flagging it.

### Distinguish Preference from Correctness
"I would have done it differently" is not a review comment. "This violates the project convention established in CLAUDE.md / `.claude/rules/architecture.md`" is.

### Check Your Assumptions
Before claiming something is wrong, verify by reading the code. Don't review from memory or pattern-match — actually trace the code path.

### Proportional Effort
A one-line typo fix doesn't need a 500-word review. A new subagent or service does. Match review depth to change scope.

### Trust-Boundary Hawk-eye
The proposal queue is the project's central invariant. Any PR that touches the boundary between agent/container and host gets extra scrutiny. The five critical anti-patterns in Step 3 are non-negotiable.
