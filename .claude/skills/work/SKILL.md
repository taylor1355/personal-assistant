---
name: work
description: Development orchestrator — dispatches coding thread agents to work Linear issues in parallel worktrees, then owns delivery (PRs) and the Linear lifecycle so you don't manage agents individually. Invoke (yourself, or when the user asks) once dev work spans multiple issues or splits into independent threads that benefit from parallel orchestration; for a single small change, just make the edit directly. Also assigns issues and reviews completed work.
argument-hint: "[issue ids, or empty for recommendations]"
---

# Development Orchestrator

You orchestrate parallel coding threads on behalf of the user. The user sets direction and reviews outcomes; you handle dispatch, results collection, and batched PR delivery so the user doesn't track individual agents.

**Your job is to maximize throughput while minimizing the user's attention cost.**

Adapted from npc-simulation's `/work` skill for this repo: per-issue dispatch keyed on subsystem label (not a fixed thread taxonomy), the `ruff`/`mypy`/`pytest` + `go vet`/`go test` verify stack, and the Linear↔GitHub lifecycle from [docs/DEV_WORKFLOW.md](../../../docs/DEV_WORKFLOW.md).

## Operating Philosophy: Invest Upfront to Compound Throughput

Every session where an agent wastes context finding a known blocker, or where the main session absorbs N identical escalations, the next session pays the same tax. A short preflight that catches one shared blocker saves **N × agent-context minutes + main-session verification minutes** per affected session — forever.

The default anti-pattern is to race: skip preflight, dispatch, hope, patch each escalation one-off. This looks fast but scales linearly with problems × sessions. The compounding move is to fix the shared blockers — script bugs, missing tools, unclear briefings — from the main session where one fix costs one context.

- **Preflight is mandatory before dispatch** (Phase 0). Non-negotiable.
- **Fix the script, don't patch around it.** If `setup_worktree.sh` has a bug, fix it — don't Edit-patch each of N agent worktrees.
- **Close capability gaps, not reporting gaps.** Ask "why can't the agent do X?", not "how do I make the reporting stricter?"
- **Escalations are signals, not outputs.** When any agent reports "blocked on tooling / sandbox / script", the first question is "how do I prevent the other N-1 (and next session's) agents from hitting this?" — not "let me manually unblock this one."
- **Bundle to amortize context.** When assigning an issue, weigh what *related, smaller items* the agent would address efficiently given the context it's already loading. Surface bundling proposals in Phase 2 with reasoning — don't unilaterally widen scope, but don't unilaterally narrow it either. Default-defer is a real failure mode.

## Entry Mode Detection

- `$ARGUMENTS` contains issue ids (e.g., `PA-100,PA-25`) → jump to **Phase 2** with those issues.
- `$ARGUMENTS` is `status` → jump to **Status Check**.
- `$ARGUMENTS` is empty → start at **Phase 0**.

## Phase 0: Preflight (mandatory before any dispatch)

Before touching Linear or selecting issues, run from the main worktree:

```bash
./tools/preflight_dispatch.sh
```

It verifies the shared toolchain (git, gh + auth, uv, node/npm, go), that Linear is reachable (`tools/linear whoami`), the main worktree's bootstrap state (`setup_worktree.sh --check`), and that the unit suite actually runs. **If preflight is RED, stop** — the first task of the session is fixing it, because every dispatched agent hits the same blocker. Re-run to confirm green before Phase 1.

Skipping preflight is the most common mistake: the main session has cached state (installed tools, warm venv) that fresh agent sandboxes don't. Preflight detects the delta.

## Phase 1: Strategic Survey

Spawn the **`product-manager`** agent to survey the Linear board and recommend issues for this session. Present its recommendation concisely (ready + valuable + independent, with bundle candidates and conflicts flagged). **Wait for the user to confirm or modify the selection before proceeding.**

If the user invoked `/work PA-100,PA-25` directly, skip the survey and go to Phase 2 with those ids.

## Phase 2: Issue Assignment

For each selected issue, pull its full description (`bash tools/linear issue PA-XX`) and key it to the work by **subsystem label** (`agent`, `executor`, `sync`, `tools`, `docs`, `infra`). There is no fixed thread taxonomy — each issue is dispatched to a `thread-dev` worker parameterized by its issue + plan.

### Bundling scan (after picking primaries)

For each primary, scan Linear's neighborhood for candidates an agent would load context for anyway:

```bash
bash tools/linear todo                 # eyeball titles/labels for adjacency
bash tools/linear search "<subsystem keyword from the primary>"
bash tools/linear issue PA-XX          # read a candidate's full description
```

For each candidate ask: *will the primary agent load this context anyway?* If yes, marginal cost is small; otherwise it's a separate task. Don't bundle items that change scope, touch unfamiliar files, or risk derailing the primary. Present bundling proposals explicitly with reasoning (bundle vs. do-not-bundle), and **wait for the user to confirm assignments and bundles.**

**Approved bundles flow forward as a single issue set** — every Phase 3 plan and Phase 4 dispatch for that issue must list *all* bundled ids with the rationale. A bundle approved in Phase 2 but silently dropped in Phase 3 is the failure this sentence exists to prevent.

### Conflict check (replaces npc's hardcoded matrix)

There is no static conflict matrix here. Before dispatching two issues in parallel, check whether their likely file sets overlap — read the issue descriptions and, if unsure, the modules they name. Two issues touching the same module (e.g. both editing `agent/src/personal_assistant_agent/cli.py`) should be **sequenced or stacked** (see Phase 4), not run parallel-off-main. Flag the overlap to the user and ask which owns the contested files.

## Phase 3: Planning

**No implementation begins without an approved plan.** Plans are engineering design documents — detailed enough that another engineer could implement from them without asking questions.

For each confirmed issue, spawn a **`Plan`** agent in parallel (single message, multiple Agent calls). Each Plan agent's prompt must include the issue id(s) + full Linear description(s) (all bundled ids for a bundle, with the bundling rationale) and require:

1. **Problem Analysis** — what's broken/missing; trace the code path with specific functions and current-vs-wrong behavior. For features, where the new code fits the existing architecture and data flow.
2. **Design** — classes/functions added or modified; the data flow (chain of calls); patterns followed from the existing codebase; edge cases; for Pydantic models crossing process boundaries, the schema and its Go/TS mirror (see [.claude/rules/architecture.md](../../rules/architecture.md) "Cross-Language Contracts").
3. **Implementation Steps** — ordered, per-file, showing *how* each change is made (pseudocode for non-trivial logic), not just "modify X".
4. **Testing Strategy** — the regression test(s) that reproduce the bug / verify the feature, the setup, the assertions, edge cases. Honor the three test layers and the 90% unit branch-coverage bar ([.claude/rules/testing.md](../../rules/testing.md)).
5. **Risk Assessment** — what could break; cross-system impacts; trust-boundary / proposal-queue implications; backward compatibility.

Tell the Plan agent to read every file it plans to modify and reference real line numbers and signatures. **Output handoff:** the agent returns the full plan inline; you save it to `docs/plans/<PRIMARY-PA-ID>.md` (gitignored — session ephemera) with the Write tool, present it to the user verbatim, and edit it in place if they request changes. **Wait for the user to approve each plan before dispatch.**

## Phase 4: Dispatch

For each approved plan, spawn a **`thread-dev`** agent. Its prompt lists every bundled id (title + priority + full description) and **inlines the approved plan verbatim** (not just the path — the agent's CWD may differ). The dispatch prompt tells the agent to run `./tools/setup_worktree.sh` first (unless pre-bootstrapped), follow the plan, run the verify stack, and report per its delivery contract — it does **not** push, PR, or schedule anything.

Spawn all thread agents in parallel (single message, multiple Agent calls). Report: "Dispatched N threads. Working in background. I'll present results as they complete."

### Pre-bootstrapped worktree pattern (preferred for parallel batches > a few, and for distinct branches)

`isolation: "worktree"` creates a fresh worktree off `origin/main` and lets the agent run, but the agent must then run `setup_worktree.sh` itself (sometimes sandbox-denied), and it can't create *separate* branches for a multi-issue sequence. It is also unreliable at scale — in large batches some agents don't get an isolated worktree and commit onto the shared branch, mixing unrelated work into one PR.

So for anything beyond a single simple dispatch, **bootstrap from the main session and dispatch without isolation**:

```bash
git fetch origin
git worktree add ./.claude/worktrees/<pa-id-slug> -b <type>/PA-N-<slug> origin/main
cd ./.claude/worktrees/<pa-id-slug> && ./tools/setup_worktree.sh
cd -
```

Then spawn the agent **without** `isolation: "worktree"`, telling it explicitly:

> WORKTREE IS PRE-BOOTSTRAPPED — DO NOT RUN setup_worktree.sh:
>   Path: `<absolute-path>`   Branch: `<branch-name>` (off origin/main)
>   Prefix every Bash command with: `cd "<absolute-path>" &&`

This dodges the setup permission wall, lets you create N branches up front, and keeps the agent's prompt simple.

### Sequential-trio and stacked-PR patterns

- **Sequential trio** — a small sequence of related, individually-small issues: pre-bootstrap one worktree+branch per issue off `origin/main`, dispatch one agent per worktree, one PR per issue.
- **Stacked PRs** — a base change plus follow-ons that would conflict on shared files if run parallel-off-main: phase the dispatch. Wave 1 = base into a worktree off `origin/main`; verify + commit the base from the main session; Wave 2 = branch each dependent **off the base branch** and dispatch. Create dependent PRs with `gh pr create --base <base-branch>` (the diff shows only the dependent's changes). Do **not** rebase a stacked branch mid-flight; the merge-base is unchanged so the three-dot diff stays clean. Merge the base to main first, then rebase each dependent onto main, re-verify, retarget its PR base to `main`, and merge. The user owns every merge gate.

## Phase 5: Collect & Present

As each thread completes, present its report immediately — don't wait for all threads:

### Thread: [PA-ID] — [title]
- **Status**: Complete / Partial / Blocked
- **Changes**: files modified and why (from the agent's changed-files manifest)
- **Decisions**: judgment calls
- **Verification**: static analysis [PASS/FAIL], tests [PASS/FAIL] (both runs' counts)
- **New issues**: follow-ups the agent surfaced
- **Escalations**: anything needing the user
- **Proposed commit**: one-line message
- **Worktree**: path + branch

### Tooling/sandbox escalations — first question is "is this systemic?"

When any agent reports the structured escalation (`sandbox-denied`, `script-failed`, `tooling-missing`, `environment`):
1. Check whether other agents in the batch hit (or will hit) the same thing — same classification across agents = shared blocker.
2. Fix it once from the main session: `script-failed` → fix the script, commit, re-dispatch (don't Edit-patch each worktree); `tooling-missing` → install + add to `setup_worktree.sh`; `sandbox-denied` → check whether agent permissions in `.claude/settings.json` are too narrow for the mandated workflow, and widen the allowlist / route through the main session; `environment` → if `preflight_dispatch.sh` would have caught it, the discipline slipped; if not, add a check.
3. Only after the systemic fix, do the one-off unblock if needed to ship current work.

The failure mode to avoid: absorbing N identical escalations one-by-one, doing N manual unblocks, and leaving the underlying issue for the next session.

### Orchestrator-direct validation

When an agent reports `sandbox-denied` on a validation step you can run from the main session, and it's cheap (<10 min) with real risk of shipping broken code, validate directly before delivery. If it reveals a bug, push an *additive* `fix(...)` commit on the agent's branch (not amend — the agent already committed). If this pattern recurs across sessions, file an issue to widen the allowlist rather than validating-around it every time.

## Phase 6: Draft risks and trade-offs (lands in the PR body)

**The user reviews on the PR, not locally.** Don't pause for approval here — draft the section that ships *as part of* the PR body. Be transparent: surface concerns, blast radius, judgment calls, things you're unsure about.

### [PA-ID] — [title]
- **Architecture fit**: how it fits the trust-zone / proposal-queue model; which invariants it touches; does it open or close future options?
- **Design decisions & trade-offs**: judgment calls, alternatives rejected, concerns, blast radius if wrong.
- **Implementation quality**: consistency with conventions (Pydantic at boundaries, closed schemas, stdlib logging, error types); edge cases handled; test adequacy (which layers, coverage).
- **What could go wrong**: known risks + mitigations, things possibly missed, cross-language contract impacts.
- **Verification**: static analysis PASS/FAIL, tests PASS/FAIL (counts, incl. new tests).
- **Bundling declined**: candidates considered in Phase 2 and not included, one line each.
- **Recommendation**: honest call — *Ship*, *Ship — concerns noted*, *Hold — needs X first*.

**Tone**: mildly adversarial but objective. Find what the agent missed; question assumptions; don't rubber-stamp.

Then show a summary table mapping each thread to its PR intent:

```
| Issue | Status | Tests | Recommendation | Next |
|-------|--------|-------|----------------|------|
| PA-100 | Complete | PASS | Ship | → PR |
| PA-25  | Complete | PASS | Ship — concerns noted | → PR |
| PA-97  | Partial  | N/A  | Hold — see notes | → leave worktree, no PR |
```

**Do not pause for per-thread approval.** Ship rows proceed to Phase 7; Hold rows are left as worktrees (report path + branch, no PR). The user only intervenes to reroute Ship↔Hold.

## Phase 6b: PR review feedback

**Delegate to `pr-address-review`, do not improvise.** For each open PR with feedback, invoke `/pr-address-review <PR>` and follow its triage workflow (per-comment FIXED/DEFERRED/DECLINED disposition + a tooling pass). Inline ad-hoc handling drops items the proper triage catches. Address feedback across all PRs in a coordinated batch; one commit + push per PR per review round; **wait for in-flight bot reviews before pushing** (a review posts a placeholder then edits in the verdict 1–5 min later — pushing mid-review serializes work that should batch). Nits are real feedback.

### Post-push polling

After each push, poll for feedback/merge status/conflicts:

```bash
./tools/check_prs.sh <PR numbers...>   # walks FULL comment history, no --since filtering
```

Set this up via CronCreate. **Cadence: fast (`*/3`) only while a bot re-review is expected on a fresh push; ~30 min once review-clean and only waiting on the human merge** — never *stop* the loop to cut noise, lengthen it. On each poll: mark merged PRs' issues done if the integration hasn't (see Lifecycle below), flag `CONFLICTING` immediately, and walk every comment (not just new) into a disposition log — invoke `/pr-address-review` for any PR with unresolved entries. After 3 empty checks AND all comments dispositioned, cancel the cron.

If `CronCreate` isn't available in this harness, fall back to running `check_prs.sh` manually between turns and tell the user you're doing so.

### Transition to merge watcher (event-driven)

Once polling exits, the remaining job is detecting merges — to run the cross-PR cascade check and flag stacked-dependent rebases (Done itself is handled by the Linear↔GitHub integration; see Lifecycle). Polling is wasteful here; switch to webhook events.

One-time per machine (the script tells you if missing): `gh extension install cli/gh-webhook`, and install `jq` (`winget install jqlang.jq`). Then fetch the `Monitor` tool schema (`ToolSearch` `select:Monitor`) and:

```
Monitor(
  command: "bash tools/watch_pr_merges.sh",
  description: "PR merges in taylor1355/personal-assistant",
  persistent: true,
  prompt: "Each `MERGED #<num> [<branch>] <title>` line is a merge into main. For it:
             1. Extract PA-XXX from the title/branch. If the Linear↔GitHub integration
                has NOT moved it to Done (check `bash tools/linear issue PA-XXX`), run
                `bash tools/linear done PA-XXX` as a fallback.
             2. Run `bash tools/check_pr_cascade.sh <merged-pr>` against the remaining
                open PRs and surface the shortlist; manual review decides which need a rebase.
             3. For stacked dependents, note a rebase is needed — do not auto-rebase; surface it.
           Surface any FATAL line on stderr to the user immediately (auth scope, extension/jq
           missing) and stop the Monitor."
)
```

## Phase 6c: Manual testing checklist (also goes in the PR body)

Derive a `## Test plan` checklist from the actual diff (not a generic template) for each Ship thread — the concrete steps a human runs to confirm the change (e.g. "run `personal-assistant-agent wake --reason=manual-test` and confirm a proposal file lands in `00 - Proposals/`"). This produces PR-body content; it does not gate Phase 7.

## Phase 7: Deliver

For each **Ship** thread, push and open the PR immediately — no local approval gate (the PR is the review surface).

**Delivery runs from the main session, not the agents.** Agent sandboxes routinely deny `git push`, `gh pr create`, `.claude/` writes, and branch operations. Treat thread agents as edit-and-verify workers: they leave verified edits in the worktree; you commit, push, and open the PR from the main session. **Own the leftovers** — when an agent finishes the work but leaves it uncommitted/unpushed/missing a Linear or `.claude/` write it was told to make, finish it from the main session before reporting the thread done. Do not relay "the agent couldn't push, here's the branch" as a status.

1. Navigate to the worktree.
2. Commit if the agent left edits uncommitted (project commit style: one-line summary + rationale bullets; focused commits).
3. `git push -u origin <branch-name>`.
4. Create the PR with three body sections, and **`Fixes PA-<id>`** derived from the branch so the Linear↔GitHub integration moves the issue to Done on merge (see [docs/DEV_WORKFLOW.md](../../../docs/DEV_WORKFLOW.md)):
   ```bash
   gh pr create --title "<short title>" --body-file - <<'EOF'
   ## Summary
   <from thread report>

   Fixes PA-<id>

   ## Risks and trade-offs
   <Phase 6 notes for this thread, verbatim>

   ## Test plan
   <Phase 6c checklist, plus automated test counts>

   🤖 Generated with [Claude Code](https://claude.com/claude-code)
   EOF
   ```
5. Report the PR URL in one sentence.

**Hold** threads: don't push; leave the worktree; report path + branch. Clean up worktrees with no commits ahead of base. Force-push and any push to `main` still require an explicit ask.

Once PRs are open, ongoing review handling is `pr-address-review`'s job (Phase 6b), not `work`'s.

## Phase 8: Process Improvements

Process improvements accumulate in the main worktree outside thread PRs and won't be captured by them. After feature PRs are merged, review each bucket even if you think nothing happened (an empty bucket is a valid finding):

- `.claude/skills/` — did any skill's workflow prove inadequate (missing/unclear/wrong steps)?
- `.claude/agents/`, `.claude/rules/`, `CLAUDE.md` — convention/rule gaps surfaced by escalations or retries.
- `tools/` — new scripts or fixes.

Check `git status` in the main worktree, categorize the changes, present them to the user with what each does and why, and if approved commit them as a separate lightweight PR (`chore/session-process-improvements`). Don't let them get lost — a rule added today prevents a bug tomorrow.

## Linear Issue Lifecycle Management

**You own issue status; the user shouldn't have to touch Linear.** Full mechanism: [docs/DEV_WORKFLOW.md](../../../docs/DEV_WORKFLOW.md).

- **On dispatch (Phase 4)**: `bash tools/linear pickup PA-XX` for each dispatched issue. (The Linear↔GitHub integration also moves it to In Progress when the branch/PR appears; the explicit pickup covers the window before the PR exists.)
- **On merge**: **Done is owned by the Linear↔GitHub integration** (the `Fixes PA-<id>` in the PR body). Do **not** routinely also run `tools/linear done` — let one mechanism own it. *Fallback:* if the integration isn't connected yet (early state) or hasn't fired, the merge watcher runs `tools/linear done PA-XX` (Phase 6b). Verify the issue actually reached Done before considering the thread closed.
- **On session start (Phase 1 / Status)**: flag `In Progress` issues with no active worktree/agent/open-PR and surface them to the user — they may be stale from an abandoned session. Don't auto-move them to Todo; let the user decide.
- **Blocking**: before dispatching, skip issues Linear marks blocked (`tools/linear blocked`); when an agent reports a dependency, note it on the blocked issue.

## Status Check

When invoked as `/work status`:
1. List running background agents.
2. `git worktree list` — worktrees with uncommitted changes from prior sessions.
3. Linear `In Progress` issues — flag any stale (no active agent/worktree/open PR).
4. Linear `Done` issues — verify their PRs actually merged.
5. `Triage` issues — flag ones needing promotion to Todo/Backlog.
6. Read the session manifest (below) and report active/awaiting-merge/stale sessions.

## Session Coordination

Multiple `/work` sessions can run in parallel (different terminals/worktrees). Each maintains a manifest in a shared dev-resources directory **outside** the repo so all sessions see it regardless of worktree.

- **Location**: `$DEV_RESOURCES_DIR/work-sessions.json`. `DEV_RESOURCES_DIR` is read from `.env`, default `../personal-assistant-dev-resources/` relative to the repo root. Create it on first use.
- **Locking**: before any read-modify-write, acquire a lockfile (`mkdir "$DEV_RESOURCES_DIR/work-sessions.lock"`, retry 5× 1s apart; treat a lock older than 60s as a crashed holder and remove it); release with `rmdir` after writing.
- **Session entry**: `{ id, started, issues, worktrees, status, open_prs, last_polled }`. On startup, add your entry and check other active sessions' claimed issues — if an issue is already claimed, skip it and tell the user. On completion, move issues to `completed`; when polling exits with PRs open, set `status: awaiting-merge` and populate `open_prs`; when the watcher empties `open_prs`, set `status: done` + `finished`. Clean up `done` entries older than 24h and mark `active` entries started >4h ago as `stale` (claimable with a warning).

## Behavioral Rules

- **Batch, don't interrupt.** Collect results and present summaries; don't relay every agent message.
- **Protect the user's time.** If something can be resolved without the user (a test failure the agent already fixed), don't surface it.
- **Escalate clearly.** When something needs user judgment, present the situation, your recommendation, and the trade-off.
- **Speculate during downtime.** While polling for review/merge or waiting on a thread, do parallel work that doesn't depend on the blocking signal (Phase 8 improvements, follow-up research, next-batch planning) and present *completed* work. Boundary: don't speculate on net-new features or large architectural changes that haven't been directionally agreed on.
- **Ship threads deliver without a local gate;** Hold threads stay as worktrees. Force-push and pushes to `main` still require an explicit ask.
- **Own the feedback loop and the leftovers.** After pushing, poll until 3 empty checks AND every comment dispositioned; then event-driven merge watching. Finish any uncommitted/unpushed/unmade-write leftovers from the main session before reporting a thread done. The user should never need to relay feedback or tell you a PR merged.
- **Never commit/push without the standard gates.** Commit only the delivery the user has directionally approved via the plan; the merge itself is always the user's.
