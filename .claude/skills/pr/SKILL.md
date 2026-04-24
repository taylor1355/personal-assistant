---
name: pr
description: Full PR preparation pipeline with iterative quality improvement. Use for all PRs.
argument-hint: "[PR number for review iteration]"
disable-model-invocation: true
---

# PR Preparation Pipeline

You are running the PR preparation pipeline. This is a multi-phase workflow with built-in iteration loops. Follow each phase in order.

**CRITICAL: Never skip phases.** Every phase exists for a reason. Even if a phase seems unnecessary for this particular PR, execute it and report its outcome. If you believe a phase has nothing to do, say "Phase N: No changes needed" rather than silently skipping it.

**Core principle: Systemic fixes over bandaids.** Before fixing any issue, ask: Does this pattern exist in other files? Could this be prevented by a project-level convention? If yes, fix the root cause, not just the instance.

## Entry Mode Detection

If `$ARGUMENTS` contains a PR number:
- If intent is clear from context (e.g., "47 address the review comments"), infer and invoke the appropriate skill.
- Otherwise, ask: **"Review this PR or address existing feedback?"**
  - **Review** → invoke `/pr-review $PR_NUMBER`
  - **Address feedback** → invoke `/pr-address-review $PR_NUMBER [user context]`

If `$ARGUMENTS` is empty:
- Run the full pipeline starting at Phase 0.

## Current Branch Context

```
!`git diff --stat origin/main...HEAD 2>/dev/null || git diff --stat HEAD~1`
```

---

## Phase 0: Scope Assessment

1. Read the full diff: `git diff origin/main...HEAD`
2. Read the commit history: `git log --oneline origin/main..HEAD`
3. Categorize the changes: new feature / bug fix / refactor / docs-only / mixed
4. List the affected systems (agent / executor / sync / config / docs) and files.
5. **Anti-pattern audit**: Read `docs/ARCHITECTURE.md` principles and any `.claude/rules/` files. Check ALL changed code against them. Flag any violations — these must be fixed before proceeding. Critical ones for this project:
   - **Proposal queue bypass**: agent code writing to the vault, sending SMS, calling calendar/email APIs directly. The only write path from the agent is `proposal_enqueue`.
   - **Unvalidated proposals**: executor code that applies a proposal without running the schema validator.
   - **Hardcoded user state**: vault paths, OAuth tokens, phone numbers, API keys in source. All must come from `config/user.yaml`, `config/providers.yaml`, or `.env`.
   - **Write credentials inside the container**: any Dockerfile layer, env_file, or compose volume that would put write-scoped API keys into the agent container.
   - **Cross-container writes outside `00 - Assistant/`**: the executor may write anywhere in the vault on the user's behalf; the agent may not.
   - **Poll loops**: the agent must be event-driven. A `while True` inside agent code is a violation.

Report your assessment before proceeding.

---

## Phase 1: Static Analysis

Spawn the `code-quality` agent in `fix-loop` mode (max 3 iterations).

The agent will run ruff + mypy on `agent/`, `go vet` on `executor/` and `sync/`, fix issues (using the `pattern-auditor` agent for systemic checks), and iterate until clean.

If the agent escalates, relay to the user. If a new anti-pattern was discovered, note it — it will be added to project rules in Phase 4.

---

## Phase 2: Test Coverage Assessment & Creation

Spawn the `code-quality` agent and ask it to assess test coverage for the current diff.

The agent will adversarially audit the diff for untested code and common blind spots (serialization roundtrips, agent↔executor contract, negative/error paths, stale API references) and identify regression test gaps for bug fixes. It will write/update tests following project standards.

After the agent reports, review its findings and write any additional tests it identified. Report: (a) what tests were created/updated, (b) coverage gaps that remain, with justification, (c) a numbered list of every new public API (Python exported names, Go exported symbols, new action types in the proposal schema) and whether it has test coverage.

---

## Phase 3: Test Execution + Convergence Gate

Spawn the `code-quality` agent in `verify` mode. It will run both static analysis and tests for Python and Go, diagnose failures, and report whether the convergence gate passes.

If the agent reports failures, fix them and re-spawn in `verify` mode. If source files were modified, the agent automatically re-runs static analysis.

**All conditions must be true before proceeding:**
- `ruff check` + `mypy` clean on Python
- `go vet` clean on both Go modules
- `pytest` passes
- `go test ./...` passes on both Go modules

If the agent escalates after 3 iterations, relay to the user with diagnosis.

Report: "Convergence gate passed: static analysis clean, all tests passing (Python + Go)."

---

## Phase 4: Documentation Updates

**CRITICAL: This phase must be thorough, not perfunctory.** Do NOT claim "docs already updated during development" without actually reading the current state of each doc and verifying accuracy. A common failure mode is assuming earlier work was complete — it often isn't, especially after subsequent refactoring.

**Procedure for each doc**: Read the CURRENT file content. Compare against the ACTUAL code behavior. Fix discrepancies. Do not trust your memory of what was written earlier in the conversation.

1. **Architecture & READMEs**: Spawn the `doc-alignment` agent in `drift` mode for the current branch's changes. It will identify stale content, inaccurate models, outdated config keys, and missing documentation for new APIs across `docs/ARCHITECTURE.md`, `README.md`, and per-module READMEs (`agent/README.md`, `executor/README.md`, `sync/README.md`). Review its findings and apply updates.

2. **Config examples**: If this PR adds or renames config keys, update `config/*.yaml.example` and `.env.example` accordingly.

3. **Anti-patterns / rules**: If new anti-patterns were discovered during Phases 0-3, add them to `CLAUDE.md` (create if missing) or a `.claude/rules/` file. Also check:
   - Did this PR introduce any patterns that SHOULD be anti-patterns? (workarounds that became permanent, shortcuts that bypassed a rule)
   - Any lessons that generalize to a rule, not just a one-off fix?

4. **Doc comments / docstrings**: Add/update docstrings on new or changed public Python functions and doc-comments on exported Go symbols. Read each new public item and verify it has a comment explaining purpose and usage.

5. **CHANGELOG** (if present): add a summary entry. If no CHANGELOG exists yet, skip this sub-step but note it as a potential follow-up.

---

## Phase 5: Change Report

Write an expert-level summary of everything that was done. This becomes the PR body. Structure:

1. **What changed and why** — 2-4 sentences covering motivation and approach
2. **Systems affected** — bullet list of components (agent / executor / sync / config / docs) touched, with brief description of changes in each
3. **Architectural decisions** — any design choices made and why (alternatives considered if relevant)
4. **Testing** — what was tested, how, coverage assessment
5. **Risks and concerns** — anything the reviewer should pay special attention to, especially around the proposal-queue invariant or cross-language contracts
6. **Follow-up work** — anything deferred or discovered that should be tracked

---

## Phase 6: Manual Verification

Generate a specific verification checklist derived from the actual changes in this PR. Do NOT produce a generic checklist.

For each test item, include:
- Exact steps to perform
- Expected behavior
- What would indicate a problem

Typical items for this project:
- If the PR touches proposal emission: "Run `make agent-wake`, confirm a proposal file appears in `var/proposals/` with valid frontmatter and body."
- If the PR touches the executor: "Drop a fixture proposal with `status: approved`, run the executor, confirm the target file was modified correctly and the proposal moved to `Applied/`."
- If the PR touches sync: "Edit a file in the user's real vault, confirm the change appears in the agent's copy within the debounce window."
- If the PR touches config: "Copy the updated `.example` over the local config and confirm the agent still starts cleanly."

### PAUSE HERE

Present the verification checklist to the user and **wait for their feedback**. Do not proceed to Phase 7 until the user responds.

- If user reports issues: fix them, re-run Phases 1-3 (convergence gate must pass again), then present updated checks covering only the new fixes.
- If user confirms everything works: proceed to Phase 7.
- If user skips some items: note skipped items as unchecked `[ ]` in the PR body.

---

## Phase 7: PR Creation

1. **Ask user for commit approval** — never commit autonomously. Present the staged changes and proposed commit message(s). Use this style:
   ```
   <type>: <short summary>

   <body — what changed and why; 1-3 short paragraphs>

   <optional bullet list of notable files or sub-changes>
   ```
   Types: `feat`, `fix`, `refactor`, `docs`, `chore`, `test`, `perf`. Create focused commits: separate bug fixes from refactoring from docs.

2. **Push and create PR**:
   ```bash
   git push -u origin <branch-name>
   gh pr create --title "<short title>" --body "$(cat <<'EOF'
   ## Summary
   <change report from Phase 5>

   ## Test plan
   <verification checklist from Phase 6 with checked/unchecked status>

   🤖 Generated with [Claude Code](https://claude.com/claude-code)
   EOF
   )"
   ```

3. Report the PR URL to the user.

---

## Phase 8: Review Iteration

When review feedback arrives on a PR created by this pipeline, invoke `/pr-address-review $PR_NUMBER` (to be created) to handle it. That skill covers the full feedback lifecycle: gather, triage, fix, push, and poll for follow-up rounds.

---

## Behavioral Rules (apply to ALL phases)

### Severity Over Order
Never go top-to-bottom through feedback. Always triage first. A correctness bug at comment #6 takes priority over a style nit at comment #1.

### Code Over Docs
When a reviewer suggests "just update the comment/docstring," read the code path first. If the code has a side effect the reviewer didn't notice, the fix is code, not docs.

### Audit Before Declaring Isolated
Never say "this is an isolated case" without searching. The search takes 30 seconds. Discovering the pattern in 4 other files takes much longer to fix later.

### Tooling Over Intuition
When evaluating whether something is a false positive, verify with tooling (linter, type checker, tests). "I recognize this pattern" is insufficient.

### Scope Discipline for Architectural Items
Large architectural changes (new proposal action types, refactoring a trust boundary, changing a protocol) should be deferred to a dedicated PR with an ADR and a tracked follow-up. The feedback-handling commit should fix bugs, not redesign systems.

### Every Review Improves the Process
If a reviewer caught something `.claude/rules/` or `docs/ARCHITECTURE.md` should have prevented, that's a gap. Don't skip the learning extraction step.

### Feature vs Quality Boundary
- **Proceed without asking**: Guard clauses, null/None checks, renaming privates, fixing internal logic, improving test coverage, adding docstrings.
- **Pause and describe first**: New public API, new files, changed user-visible behavior, architectural changes, new proposal action types.

### Communication
- Log phase transitions explicitly: "Phase 1 complete: static analysis clean after 2 fix rounds. Proceeding to test assessment."
- When escalating, include: what the issue is, what was tried, why it didn't work, and a proposed path forward.

### Test Integrity
- Never delete tests to make the suite pass.
- Never loosen assertions as a fix.
- Never suppress lint/type warnings without fixing the underlying issue.
- Never write trivial tests for coverage padding.
- If a test is hard to write, consider whether the source code needs refactoring.
