# Architecture Rules

Project-specific principles, expanded from [CLAUDE.md](../../CLAUDE.md). Full design context lives in [docs/ARCHITECTURE.md](../../docs/ARCHITECTURE.md); this file is the working reference for code review and `/audit` runs.

## Three Trust Zones

```
┌─ container (untrusted) ────────────────────────────────────────┐
│ agent: Python + NeMo. Read-only Gmail, Calendar, vault copy,   │
│ Linear (team-scoped). Holds NO write creds for user state.     │
│ Compromise → bad proposals + token spend, nothing more.        │
└────────────────────────────────────────────────────────────────┘
                               │ proposals (file)
                               ▼
┌─ host (trusted) ───────────────────────────────────────────────┐
│ executor   applies vault/calendar/email writes from approved   │
│            proposals; audit-logs every applied one             │
│ dispatcher debounces triggers; invokes agent CLI with batch    │
│ sms        Twilio webhook → agent; outbound REST               │
│ sync       two-way vault sync                                  │
│ devops     v2: PR submission to allowed repos                  │
└────────────────────────────────────────────────────────────────┘
```

The trust boundary is the only thing keeping a compromised agent from doing real harm. Any change that crosses it (giving the agent a write cred, allowing it to push directly somewhere) is a critical review item — flag it as ARCHITECTURE BREAKING in audit.

## The Proposal Queue Invariant

Every irreversible mutation goes through a proposal file. Spec: [docs/PROPOSAL_FORMAT.md](../../docs/PROPOSAL_FORMAT.md).

- Agent code MUST NOT call any API or filesystem path that mutates user state without going through `proposal_enqueue` (or, for auto-applied Linear ops, through `LinearClient`).
- The Python `proposal_enqueue` validates the proposal *before* writing the file. The Go executor revalidates *before* applying. Double validation is intentional — the agent container is untrusted.
- Auto-applied actions are still emitted as proposal files for audit. The executor processes them by skipping the user-approval wait, not by skipping the file.

If you find yourself writing code that wants to mutate state directly because "it's just a small thing," stop. Either it's safe enough to be auto-applied (and goes through `LinearClient` or a future `linear_*` action type), or it isn't and needs the full proposal flow.

## Agentic Dispatch

A root agent receives the wake trigger and decides which subagent(s) to invoke. Subagents are specialists; the root is glue.

- Subagents have a single responsibility expressible as one sentence (`journal_agent` reads today's journal and proposes todo completions).
- Subagents do not call each other directly. The root invokes them; the result lands in the wake's session log.
- Shared tools (`vault_read`, `proposal_enqueue`, `linear_cli`, `sms_send`) are stateless and reusable. They have no awareness of which subagent calls them.

This shape lets you swap a subagent's prompt or model without touching anything else, and lets the root reason about budget+priority across all candidates per wake.

## Value-Prioritized Wakes

Every wake answers "what's the most valuable thing I can do right now?" Ranked tiers:

1. **Time-sensitive obligation** — SMS reply owed, imminent calendar item, todo-completion detection on a fresh journal entry, Linear issue with deadline < 24 hr
2. **Advanceable user interest** — top of Linear `Todo` by priority, in-progress issue that can advance, vault-organization that's the next blocker
3. **Long-horizon backburner** — research issues, exploratory work, R&D programs

Mid-wake escalation is allowed (an investigation reveals an obligation). Mid-wake de-escalation isn't (you don't quietly demote an obligation to backburner work).

Tier-1 can run over the soft budget cap; only the hard daily/weekly caps actually block. Tier-2 and tier-3 self-throttle. See [docs/BUDGET.md](../../docs/BUDGET.md).

## Linear and Obsidian Have Distinct Purposes

- **Linear** = issue tracking, dependencies, status, dev work. Accessed via `tools/linear` and `LinearClient`.
- **Obsidian + Bases** = knowledge, journals, projects, plans, todos, working notes. Bases queries provide organizational dashboards over the user's content.
- **No mirror** between them. Don't propose creating issue files in the vault; don't propose creating notes that duplicate Linear data.

Linear has its own UI; the vault doesn't reproduce issue lists. Bases earns its keep over user-content frontmatter, not over Linear-shaped data.

## Cross-Language Contracts

Three languages, one schema where they meet:

- **Proposal frontmatter**: Pydantic on the Python side, mirrored Go struct on the executor side. Adding a field requires updating both *and* [docs/PROPOSAL_FORMAT.md](../../docs/PROPOSAL_FORMAT.md) in the same PR.
- **Linear CLI input/output**: TS-defined; Python `LinearClient` consumes stdout as opaque strings (passed to LLM) for reads, and uses JSON-stdin for writes. Don't parse the human-readable read output in Python — if a structured form is needed, add JSON output to the CLI.
- **Wake event payloads**: Go dispatcher writes JSON; Python CLI parses with Pydantic. Same shape on both sides.

Schema drift across this boundary is the classic source of integration bugs. The closed Pydantic schema (`extra="forbid"`) is what makes the bug surface immediately rather than after weeks of silent data loss.

## Anti-pattern Table

| Anti-pattern | Why it's bad | What to do instead |
|---|---|---|
| Agent writes to user state directly | Breaks proposal-queue invariant; bypasses audit log | `proposal_enqueue` (or `LinearClient` for auto-applied Linear) |
| Executor accepts unvalidated proposals | One bad agent run → corrupted vault | Validate against schema before adapter runs |
| Hardcoded user paths / accounts / keys | Breaks reusability | `config/*.yaml` or `.env` |
| Write creds in the agent container | Compromise → unbounded blast radius | Host-side services hold creds |
| Poll loops in agent code (`while True:`) | Burns tokens; conflates wakes | Event-driven; one wake per trigger |
| Silent `if not x: return` at boundaries | Hides real bugs | Log + return; surface what was unexpected |
| Mocking the proposal-queue invariant in tests | If a test needs to mock it, the code is violating it | Fix the code |
| Magic strings for action types / Linear states / labels | Drift across languages | Pydantic enums / Go consts / TS unions |
| Bare `except:` / catching `Exception` broadly | Hides bugs; eats keyboard interrupts | Catch specific types; let others propagate |
| Mutable default args (`def f(xs=[])`) | Shared mutable state across calls | `def f(xs=None): xs = xs or []` |
| Tests with no regression value (tautological) | Wasted test space | See [.claude/rules/testing.md](testing.md) |
| Going around `LinearClient` for Linear ops | Two paths means two places to fix | Add a method to `LinearClient`; everyone uses one |
| Cross-system writes outside `00 - Assistant/` without proposal | Direct mutation of user content | All vault writes outside `00 - Assistant/` need a user-approved proposal |
| Re-implementing functionality already in `tools/linear` or `tools/linear-pm` | Two implementations diverge | Extend the existing CLI |
| Skipping validation "because it's internal" | Internal contracts break too | Validate at every process boundary |

When auditing, treat the first 5 items as automatic CRITICAL findings — they break the trust model.

## What's Not in Scope of These Rules

- Logic inside individual subagents (their prompts, their reasoning patterns) — that's a per-subagent concern
- Choices of LLM provider per task — that's `config/providers.yaml`
- Specific vault organization decisions — that's [docs/VAULT_ORGANIZATION.md](../../docs/VAULT_ORGANIZATION.md)
- Specific Linear conventions — that's [docs/LINEAR_CONVENTIONS.md](../../docs/LINEAR_CONVENTIONS.md)

This file is the project's invariants — change here implies changing everything.
