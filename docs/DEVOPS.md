# Dev work (v2)

Spec for the agent's ability to author and submit pull requests. **Not in v1** — included here so v1 plumbing makes the right choices for what comes next.

## Purpose

The agent picks up code-typed Linear issues — including issues against this very repo — and ships them as PRs. The user reviews PRs the way they'd review any contribution. PR review is the natural approval gate; no special proposal needed.

## Trust boundary

A new host-side service: `devops`. It holds GitHub credentials and is the only component allowed to push to GitHub.

```
agent (container)                  devops (host)                  GitHub
  - emits "ready to PR" proposal     - reads approved proposal       - PR landed for user review
  - includes patch + test results    - clones / checks out worktree   - existing CI runs
                                     - applies patch
                                     - re-runs tests on host
                                     - pushes branch + opens PR
                                     - reports URL back
```

The agent never holds `GITHUB_TOKEN`. The agent never pushes. The devops service is the privileged actor.

## Issue dispatch

Linear issues that route to `devops_agent`:

- Type label is one of `feature` / `bug` / `tech-debt`
- A `repo: <name>` label specifies which repo (e.g., `repo: personal-assistant`, `repo: npc`)
- The repo appears in `GITHUB_ALLOWED_REPOS` (env var, comma-separated)
- The issue body follows the dev-issue template (see [LINEAR_CONVENTIONS.md](LINEAR_CONVENTIONS.md))

The root agent ranks these alongside other tier-2 work; `devops_agent` runs only when a code issue is the chosen action.

## Workflow

The agent's `devops_agent` follows the existing dev-time `pr` skill (`.claude/skills/pr/SKILL.md`) verbatim — that skill IS the runbook for shipping a PR. Specifically:

1. **Phase 0 — Scope assessment.** Read the issue, read the diff against `main`, classify the change. The same anti-pattern audit runs (proposal-queue bypass detection becomes critical for self-PRs).
2. **Phase 1 — Static analysis.** `code-quality` agent in `fix-loop` mode.
3. **Phase 2 — Test coverage.** `code-quality` agent assesses; agent writes the missing tests.
4. **Phase 3 — Convergence gate.** Static analysis clean, tests pass.
5. **Phase 4 — Documentation.** `doc-alignment` agent in `drift` mode for the changed area; updates docs as needed.
6. **Phase 5 — Change report.** Becomes the PR body.
7. **Phase 6 — Verification checklist.** Becomes the test-plan section in the PR body. The agent doesn't pause for user feedback at this step (the PR review IS the feedback); it just notes any items that should be human-verified.
8. **Phase 7 — PR creation.** The agent emits a "ready to PR" proposal containing the patch, branch name, commit message(s), and PR title/body. The devops service applies it: clones the repo (or fetches the branch from a managed worktree pool), applies the patch, runs the local test suite once more on the host (defense in depth), pushes the branch, opens the PR via `gh`.
9. **Phase 8 — Review iteration.** Reviewer feedback (Gemini auto-reviewer if wired, GitHub Copilot, the user) lands as comments. A scheduled trigger wakes the agent to address review per the `pr-address-review` skill (TBD — port from npc-simulation when this is built).

## Sandboxing

The devops service maintains a worktree pool under `var/devops/worktrees/<repo>/<branch>/`. Each issue gets its own worktree so concurrent dev work doesn't trip on itself. Worktrees are pruned when the PR merges or after N days of inactivity.

The agent's container does NOT see these worktrees. The agent works from a snapshot of the repo it can read (vault-style read mount), produces a patch, and the devops service applies it in the worktree. This keeps the trust boundary clean: agent compromise → bad patch → reviewer rejects → no harm.

## Allowed repos

`GITHUB_ALLOWED_REPOS` controls which repos the devops service will accept patches for. Format: comma-separated `owner/repo`. Default for v2: `taylor1355/personal-assistant` only — the agent improves itself first. Other repos added explicitly.

A patch for a repo not on the allowlist is rejected at the proposal-validation layer; the agent gets the rejection back as a tool error.

## Self-PR safety

When the agent PRs against `personal-assistant` itself:

- The diff cannot remove approval gates without an explicit user-approved proposal first. Specifically: changing `auto-applied` action types in the executor's allowlist requires a separate proposal that lands BEFORE the dev-PR.
- The diff cannot widen `GITHUB_ALLOWED_REPOS`. That env var is host-side; the agent can't change it via PR.
- The diff cannot weaken the budget caps. (Same env-var trick: budget caps are config, not code, and config is host-side `.env`.)
- All anti-patterns from `.claude/skills/pr/` Phase 0 still apply, with proposal-queue bypass and unvalidated-executor-input being treated as automatic CRITICAL findings that block the PR.

These protections live in the `code-quality` agent's audit logic and in the `pattern-auditor`'s anti-pattern table. They're enforced by the agent on itself; CI (when it exists) re-runs them.

## CI

External to this spec but expected: GitHub Actions on `personal-assistant` runs `code-quality` checks on every PR. The auto-reviewer (port from npc-simulation, on the open-todos list) reviews diffs from the agent the same way it'd review a human's. Agent and human PRs are reviewed by the same gates.

## What this enables — and what it doesn't

**Enables:**
- Agent picks up "add a `vault-create` adapter" issue, ships PR, you review and merge.
- Agent picks up "research X and write a synthesis note" — non-dev work — and outputs land in the vault, not as a PR.
- Multi-step refactors broken into Linear sub-issues, each landing as its own small PR.

**Doesn't:**
- Direct push, force-push, or branch deletion. PR is the only output.
- Cross-repo changes in a single PR. One repo per PR.
- Modifications to user accounts, billing, third-party services. The agent affects code; humans approve everything else.

## Dependencies

Lands when:
- v1 is stable (intake, dispatcher, value-priority, Linear, vault-org)
- A non-trivial Linear backlog exists for the agent to draw from (so dev work is a real allocation choice, not a contrived demo)
- The dev-time `pr` skill has run successfully against this repo a few times by the user (so we know the runbook works)

Probably 1–2 months after v1 ships, depending on how the v1 backlog accumulates.
