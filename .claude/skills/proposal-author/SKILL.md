---
name: proposal-author
description: Draft a structured proposal file (frontmatter + body + diff preview) for the proposal queue. Enforces schema, naming, and target-path conventions. The agent container's ONLY path to mutating user state — never bypass.
argument-hint: "[action type] [short description], or empty to interview"
---

# Proposal Author

You are drafting a proposal for the agent's proposal queue. Every write the assistant wants to make — to the vault, calendar, email, anywhere — flows through this skill. The executor applies proposals only after the user approves them by editing frontmatter.

**Central invariant: the agent container never mutates user state directly. If your output is not a proposal file, you are violating the invariant.** Read `docs/ARCHITECTURE.md#the-proposal-queue` if you are unsure why.

## Inputs

The caller provides:
- **Action type** — one of the registered action types (see below). If unclear, ask.
- **Target** — the specific thing being modified (file path for vault, event ID for calendar, etc.).
- **Intent** — a human-readable sentence describing what the user will gain by approving.
- **Content** — the actual change: a diff for vault edits, a payload for calendar/email.
- **Reasoning** — why this change is being proposed now; what observation triggered it.

If any of these are missing and you're being invoked interactively, interview the caller for them before writing anything.

## Registered action types

Only these are supported by the executor. Do not invent new types without adding a validator and adapter on the Go side; otherwise the proposal will be rejected.

| `action` | Target kind | Body must contain |
|---|---|---|
| `vault_edit` | Vault file path (relative to vault root) | Unified diff OR full replacement text with explicit `mode: diff\|replace` |
| `vault_create` | Vault file path (must not exist) | Full file content |
| `vault_delete` | Vault file path (must exist) | Reason (body text); executor moves to `00 - Assistant/Trash/`, not hard delete |
| `calendar_create` | Calendar name + event object | Event fields per Google Calendar API |
| `calendar_update` | Calendar event ID | Fields to change |
| `calendar_delete` | Calendar event ID | Reason |
| `email_draft` | Gmail thread ID (optional) | Full RFC 5322 message body |
| `email_label` | Gmail message ID | Labels to add/remove |
| `email_archive` | Gmail message ID | — |

More types will be added as subagents grow. If a user need doesn't fit any existing type, stop and escalate — do not force-fit.

## Output format

Write exactly one file to `$PROPOSALS_PATH` (defaults to `/data/proposals` inside the container). Name format:

```
YYYY-MM-DD-HHMM-<slug>.md
```

- Timestamp is UTC, to the minute. Two proposals in the same minute differentiate by slug.
- Slug is kebab-case, ≤40 chars, summarizing the action (e.g., `check-off-gym-todo`, `archive-dated-plan-beach-trip`).

Frontmatter (YAML) — required fields:

```yaml
---
proposed_at: 2026-04-24T14:30:00Z        # ISO 8601 UTC, matches filename timestamp
agent: journal_agent                      # subagent that drafted this
action: vault_edit                        # one of the registered types above
target: "02 - Todos/01 - Short Term Todos.md"   # path, ID, or other identifier per action
status: pending                           # always `pending` on write; user changes to `approved` / `rejected`
mode: diff                                # action-specific; omit if not applicable
---
```

Body structure (markdown):

```markdown
## Intent
One-sentence, human-readable: what changes if the user approves this.

## Reasoning
Why this change is being proposed now. Cite the observation that triggered
it (journal entry line, calendar conflict, email content, etc.). Link to
source notes with `[[wiki-links]]` when the source is in the vault.

## Change

<!-- For vault_edit with mode: diff -->
```diff
--- a/02 - Todos/01 - Short Term Todos.md
+++ b/02 - Todos/01 - Short Term Todos.md
@@ -12,3 +12,3 @@
 ### Health
-- Gym 3x this week
+- ~~Gym 3x this week~~ done
 - Drink more water
```

<!-- For vault_create / replace -->
```markdown
<full file content inside a fenced block; note the language tag>
```

<!-- For calendar/email -->
```yaml
<the API payload the executor will send>
```

## Notes
Optional — anything else the user should know before approving (ambiguity
the agent had, alternatives considered, follow-ups that might be needed).
```

## Writing discipline

1. **One change per proposal.** If the journal mentions three completed todos, write three proposals — not one omnibus. The user must be able to approve/reject each independently.
2. **Quote the evidence.** In the Reasoning block, include the specific text that triggered the proposal (a journal line, an email subject). The user should not need to open a second file to evaluate.
3. **Preview the exact change.** Never describe it abstractly when a diff or payload is available. The diff IS the contract with the executor.
4. **Respect the vault's shape.** For vault proposals, follow the conventions in `docs/ARCHITECTURE.md#vault-handling` — wiki-links over markdown links, append to existing files before creating new ones, no frontmatter outside `98 - Literature Notes/` and `00 - Assistant/`. When the proposal IS about improving vault organization, note that explicitly in Intent.
5. **No side effects from this skill.** This skill only writes to `$PROPOSALS_PATH`. It does not send SMS, call external APIs, or touch any other state. Any of those are violations and should be refactored into their own proposal types.

## Validation before write

Before writing the file, self-check:

- [ ] `action` is in the registered types table
- [ ] `target` is valid for that action (path exists for `vault_edit`/`vault_delete`; path doesn't exist for `vault_create`)
- [ ] Frontmatter has `proposed_at`, `agent`, `action`, `target`, `status: pending`
- [ ] Body has Intent, Reasoning, Change sections
- [ ] For diff-mode vault edits: the diff is valid unified-diff format with correct line numbers
- [ ] Filename matches `YYYY-MM-DD-HHMM-<slug>.md`
- [ ] Slug is ≤40 chars, kebab-case, descriptive

If any check fails, fix before writing. A malformed proposal is worse than no proposal — the executor will reject it and the intent is lost.

## Failure modes to avoid

- **Writing directly instead of proposing.** If you find yourself about to call the vault writer, stop. Write a proposal instead.
- **Batching unrelated changes.** Each proposal = one approve/reject decision. Unrelated changes go in separate files.
- **Optimistic diffs.** If the target file's content at the time the executor applies the proposal might have changed (user may have edited between proposal and approval), prefer a 3-way merge mode or include enough context lines that the diff remains applicable.
- **Silent schema drift.** If you need a field not in the table above, you need to update the executor's validator first. Propose the schema change as its own proposal (meta-proposal) — do not just add the field.
