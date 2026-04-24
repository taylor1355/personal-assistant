---
name: audit
description: Adversarial codebase audit — finds bugs, gaps, stale docs, missing tests, and debt. Point at a directory or let it roam.
argument-hint: "[path or system name, or empty for autonomous exploration]"
---

# Codebase Audit

You are running an adversarial audit. Your job is to find problems — not confirm things work. Assume there ARE issues. A clean report is suspicious; dig deeper.

**Mindset**: You are an external reviewer who doesn't trust the code. Every "this looks fine" should be followed by "but let me verify." Fight the instinct to rubber-stamp.

## Entry Mode

**If `$ARGUMENTS` is a path** (e.g., `agent/src/personal_assistant_agent/tools`, `executor/internal`, `docs`):
- Audit that directory specifically. Read files, check for issues.

**If `$ARGUMENTS` is a system name** (e.g., "proposal queue", "sync", "provider routing", "subagent journal"):
- Find all files related to that system across `agent/`, `executor/`, `sync/`, `config/`, and `docs/`. Audit them holistically.

**If `$ARGUMENTS` starts with `post-merge`** (e.g., `post-merge`, `post-merge 3`, `post-merge abc123`):
- **Post-merge mode.** Scoped audit of what just landed on `main`.
- Parse the optional argument: a number means "last N merges", a hash means "since that commit". Default: last 1 merge.
- Run the **Verification Steps** (below) first, then audit only the changed files through all dimensions.

**If `$ARGUMENTS` is empty**:
- Autonomous mode. Identify high-risk areas and troll through them. Start with recently changed files (`git log --oneline -20`), then follow dependencies.

---

## Audit Dimensions

For each file or system you examine, check ALL of these. Report findings organized by severity.

### 1. Correctness
- Do functions do what their names/docs say?
- Are there off-by-one errors, wrong comparisons, inverted conditions?
- Do edge cases crash or silently do the wrong thing? (null inputs, empty collections, zero/negative values, boundary values)
- Are there race conditions or ordering dependencies? (goroutine lifecycle, asyncio tasks, filesystem event debouncing, proposal-file transitions)
- Do serialization roundtrips preserve all state? (proposal frontmatter → executor parse → adapter input; config YAML → Pydantic models; Go JSON encode/decode)

### 2. Completeness
- Are there TODO/FIXME/HACK comments that represent real gaps?
- Are there stub methods that return dummy values or no-op?
- Are there features partially implemented? (data structure exists but nothing reads it; action type declared in schema but no adapter registered)
- Are there dead code paths that will never execute?
- Are there missing error handling paths?

### 3. Consistency
- Do similar systems follow similar patterns? (subagent definitions, tool interfaces, executor adapters)
- Are naming conventions followed? (snake_case for Python, CamelCase for Go exports, `YYYY-MM-DD-HHMM-<slug>.md` for proposals)
- Are parameter values consistent across docs and code? (timeouts, poll intervals, path defaults)
- Do doc comments match actual behavior?

### 4. Test Coverage
- For each public function: does a test exist? Does it test the RIGHT thing?
- For each bug fix in recent history: does a regression test exist?
- Are tests testing behavior or implementation details?
- Are there tests that always pass regardless of code changes? (tautological assertions)
- Are there tests that reference stale APIs or old parameter values?

### 5. Documentation
Spawn the **doc-alignment** agent in `drift` mode for the audited area. It will check whether `docs/ARCHITECTURE.md`, `README.md`, and per-module READMEs still match current behavior. Review its findings and include in your report.

### 6. Architecture
- Does code respect `docs/ARCHITECTURE.md` invariants? In particular:
  - **Proposal queue invariant**: agent code never mutates user state outside `/data/proposals` and `00 - Assistant/` writes via executor.
  - **Three-zone trust model**: no write credentials inside the agent container; executor never reads proposals it didn't validate.
  - **Event-driven wakes**: no long-running poll loops inside the agent.
- Are there coupling violations? (subagent reaching into another subagent's internals; agent tool directly touching the sync service)
- Are there abstraction leaks? (provider-specific types escaping the provider abstraction; Pydantic models leaking into the Go side's JSON contract)
- Is complexity in the right place? (business logic in CLI code, agent logic in executor adapters)

### 7. Performance (when relevant)
- Are there O(n²) patterns that could be O(n)?
- Are there filesystem scans that should be watchers?
- Are there LLM calls that could be cached (prompt caching) or batched?
- Are there per-wake allocations that leak memory across wakes?

---

## Verification Steps (post-merge mode, or on request)

These steps execute tools rather than just reading code. Run them when in post-merge mode, or when the user requests verification during any audit mode.

### 8. Static Analysis + Test Execution
Spawn the **code-quality** agent in `audit` mode. It will:
- Run static analysis (`ruff check`, `mypy`, `go vet`) and classify each issue as introduced vs pre-existing
- Run tests (`pytest`, `go test ./...`) and diagnose whether failures are caused by audited changes
- Flag suspicious patterns (test count decreased, suspiciously fast runs, skipped tests added silently)

Report introduced issues as 🔴 CRITICAL, pre-existing as 🟠 MEDIUM.

### 9. CHANGELOG & Docs Check
- Were the changes reflected in `CHANGELOG.md` (if present) or the repo's release notes?
- Were `docs/ARCHITECTURE.md` sections updated where they describe behavior that changed?

---

## Reporting Format

Organize findings by severity:

### 🔴 CRITICAL (blocks correctness, data loss, security)
For each: file, line, what's wrong, why it matters, proposed fix.

Special attention — these are CRITICAL regardless of blast radius:
- Any path by which the agent mutates user state outside the proposal queue
- Any unvalidated proposal reaching the executor
- Any hardcoded credential, OAuth token, phone number, or vault path

### 🟡 HIGH (significant quality/correctness concern)
For each: file, line, what's wrong, impact, proposed fix.

### 🟠 MEDIUM (should fix but not blocking)
For each: file, what's wrong, recommendation.

### 🔵 LOW (nits, style, minor improvements)
Brief list.

### ✅ VERIFIED CORRECT
List things you checked that ARE correct — this proves you actually looked rather than just listing problems.

---

## Behavioral Rules

### Don't
- Don't rubber-stamp. "Looks fine" is not an audit finding.
- Don't only check recently changed code. Old code has bugs too.
- Don't trust your memory from earlier in the conversation. Read the file.
- Don't report stylistic preferences as bugs. Focus on correctness.
- Don't hallucinate issues. If you're not sure, say "UNVERIFIED" and explain what you'd need to check.

### Do
- Read actual file contents before reporting issues. Quote line numbers.
- Follow dependency chains. If A calls B, check both — especially across the agent/executor boundary.
- Check both the happy path and the error path.
- Verify that tests actually test what they claim to test.
- Cross-reference docs against code, not just check that docs exist.
- Report when something is surprisingly well-done — positive findings build trust in the audit.

### When to stop
- If `$ARGUMENTS` specified a target: audit that target thoroughly, then stop.
- If autonomous mode: spend ~15-20 minutes of exploration, report findings, then ask if the user wants you to continue or focus on a specific area.
- Always end with a summary: X critical, Y high, Z medium findings. Plus a recommendation for where to audit next.
