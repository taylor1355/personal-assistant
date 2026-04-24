# Proposal Format

Specification for the proposal-queue file format. Anything emitted by the agent and consumed by the executor MUST conform to this document. Referenced from [ARCHITECTURE.md](ARCHITECTURE.md#the-proposal-queue).

The agent-side tool that writes proposals is `proposal_enqueue` (Python, in `agent/src/personal_assistant_agent/tools/`). The executor-side validator (Go, in `executor/internal/proposals/`) parses and verifies proposals before any adapter runs.

## Location and lifecycle

- **Written to** (inside the container): `$PROPOSALS_PATH`, default `/data/proposals/`.
- **User reviews** the file in Obsidian (the sync service exposes the proposals folder under `00 - Assistant/Proposals/` in the real vault).
- **User approves** by editing frontmatter `status: pending → approved` (or `→ rejected`).
- **Executor applies** approved proposals, transitions to `status: applied` (or `failed`) with a result block appended, then moves the file to `00 - Assistant/Proposals/Applied/YYYY-MM/`.

## Filename

```
YYYY-MM-DD-HHMM-<slug>.md
```

- Timestamp is UTC, to the minute, matching `proposed_at` in frontmatter.
- Two proposals in the same minute differentiate by slug.
- Slug is kebab-case, ≤40 chars, summarizing the action (e.g., `check-off-gym-todo`, `archive-dated-plan-beach-trip`).

## Frontmatter schema

```yaml
---
proposed_at: 2026-04-24T14:30:00Z          # ISO 8601 UTC
agent: journal_agent                        # subagent that drafted this
action: vault_edit                          # one of the registered types below
target: "02 - Todos/01 - Short Term Todos.md"   # path, ID, or other identifier per action
status: pending                             # pending | approved | rejected | applied | failed
mode: diff                                  # action-specific; omit if not applicable
---
```

All fields are required except `mode`. The executor rejects proposals with extra unknown keys to prevent silent schema drift.

## Registered action types

Only these are supported. Adding a new type requires a PR that updates both the Python tool (schema) and the Go executor (validator + adapter).

| `action` | Target kind | Body must contain |
|---|---|---|
| `vault_edit` | Vault file path (relative to vault root) | Unified diff OR full replacement text; set `mode: diff` or `mode: replace` |
| `vault_create` | Vault file path (must not exist) | Full file content |
| `vault_delete` | Vault file path (must exist) | Reason in body; executor moves to `00 - Assistant/Trash/`, not hard delete |
| `calendar_create` | Calendar name + event object | Event fields per Google Calendar API |
| `calendar_update` | Calendar event ID | Fields to change |
| `calendar_delete` | Calendar event ID | Reason |
| `email_draft` | Gmail thread ID (optional) | Full RFC 5322 message body |
| `email_label` | Gmail message ID | Labels to add/remove |
| `email_archive` | Gmail message ID | — |

## Body structure

```markdown
## Intent
One-sentence, human-readable: what changes if the user approves this.

## Reasoning
Why this change is being proposed now. Cite the observation that
triggered it (journal line, calendar conflict, email content). Use
`[[wiki-links]]` when the source is in the vault.

## Change

<!-- vault_edit, mode: diff -->
```diff
--- a/02 - Todos/01 - Short Term Todos.md
+++ b/02 - Todos/01 - Short Term Todos.md
@@ -12,3 +12,3 @@
 ### Health
-- Gym 3x this week
+- ~~Gym 3x this week~~ done
 - Drink more water
```

<!-- vault_create, vault_edit mode: replace -->
```markdown
<full file content inside a fenced block with language tag>
```

<!-- calendar_*, email_* -->
```yaml
<the API payload the executor will send>
```

## Notes
Optional. Anything else the user should know before approving (ambiguity
the agent had, alternatives considered, follow-ups this might need).
```

## Discipline for emitting proposals

1. **One change per proposal.** If the journal mentions three completed todos, write three proposals. The user must be able to approve or reject each independently.
2. **Quote the evidence.** The Reasoning block must include the specific text that triggered the proposal. The user should not need to open a second file to evaluate.
3. **Preview the exact change.** Never describe a change abstractly when a diff or payload is available. The diff IS the contract with the executor.
4. **Respect the vault's shape.** For vault proposals, follow [ARCHITECTURE.md#vault-handling](ARCHITECTURE.md#vault-handling) — wiki-links over markdown links, append to existing files before creating new ones. When the proposal itself is about improving vault organization (adding frontmatter, tags, MOCs), state that explicitly in Intent.
5. **No side effects from the emit path.** The tool only writes a proposal file. Sending SMS, calling external APIs, or mutating any other state from within a proposal-emission code path is a violation.

## Validation

The Python `proposal_enqueue` tool MUST validate before writing:

- `action` is in the registered types table
- `target` is valid for that action (path exists for `vault_edit`/`vault_delete`; path doesn't exist for `vault_create`)
- Frontmatter has all required fields
- Body has Intent, Reasoning, Change sections
- For `mode: diff` vault edits: the diff is valid unified-diff format with correct line numbers
- Filename matches `YYYY-MM-DD-HHMM-<slug>.md`
- Slug is ≤40 chars, kebab-case

The Go executor re-validates against the same schema before applying. Double validation is intentional: the agent container is untrusted; the executor cannot assume the agent's output is well-formed.

## Failure modes

- **Direct mutation**: agent code that writes outside the proposal queue. Critical violation; fix the agent code.
- **Omnibus proposals**: batching unrelated changes into one file. Split into multiple proposals.
- **Optimistic diffs**: if the target file might be edited by the user between proposal and approval, either use `mode: replace` or include enough context lines that the diff still applies.
- **Silent schema drift**: adding a frontmatter field not in this spec. The executor will reject. Update this spec, the Python tool, and the Go validator together — in that order.
