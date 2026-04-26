# Linear Conventions

Adapted from `taylor1355/npc-simulation`'s conventions, generalized for personal-assistant. The agent enforces these defaults; the user can override per-issue.

## Workspace shape

- One team: **Personal Assistant**, key `PA`. All issues are `PA-N`.
- Initiatives, projects, cycles: optional. Use as scope grows. v1 starts with no projects; the agent creates them when natural clusters of issues form (e.g., a "Vault organization" project once 5+ vault-org issues exist).

## Labels

Labels are typed. Each issue carries one label per type, plus optional strategic labels. Labels live in Linear directly — no mirror.

### Type (required, one)

| Label | Use |
|---|---|
| `feature` | New capability, code change for personal-assistant or another repo |
| `bug` | Something broken — agent or user-side |
| `tech-debt` | Cleanup, refactor, deferred fix |
| `investigation` | Open question that needs research before action |
| `docs` | Documentation work |
| `life-task` | Real-world task (errand, appointment to schedule, person to contact) |
| `research` | Multi-step research deliverable, deep work |
| `vault-organization` | Vault frontmatter, Bases views, MOC creation, restructuring |
| `reading` | Books to read, articles to digest, courses to follow |
| `health` | Habits, fitness, medical |
| `relationship` | People-related (call X, plan Y for partner, send card) |

### Subsystem (optional, 0–2)

For dev-typed issues only. Names the area of code. Repo-specific; for personal-assistant: `agent`, `executor`, `sync`, `dispatcher`, `sms`, `devops`, `linear-tool`, `docs`, `infra`. Other repos get their own subsystem labels as the agent picks them up.

### Strategic (optional)

| Label | Use |
|---|---|
| `urgent` | Time-pressing; bumps tier-1 priority |
| `quick-win` | <30 min; agent can fit into spare wake cycles |
| `keystone` | Unblocks ≥3 other issues; prioritize when actionable |
| `experiment` | Try-it-and-see; OK to abandon |
| `ongoing` | Recurring, doesn't fully complete (e.g., "weekly review") |

## Priority

Linear's native scale, used as-is:

| Value | Name | Default rule |
|---|---|---|
| 1 | Urgent | <24 hr deadline OR explicitly user-flagged |
| 2 | High | This week, important |
| 3 | Medium (default) | Backlog, no specific deadline |
| 4 | Low | Nice-to-have, minimal cost if dropped |
| 0 | None / Triage | New issues land here until `pm_agent` triages |

## States

Mapped to Linear's standard workflow states:

| State | Meaning |
|---|---|
| `Triage` | Default for newly-created issues until classified |
| `Backlog` | Classified, not active |
| `Todo` | Ready to pick up; no blockers |
| `In Progress` | Currently being worked on |
| `Blocked` | Waiting on something external (user input, API, another issue) |
| `Done` | Completed |
| `Canceled` | Abandoned without completion (gated transition; agent must explain) |

## Issue templates

The agent uses these templates when creating issues. Required sections marked.

### Generic

```markdown
## Context (required)
What triggered this? (journal entry, user instruction, agent observation)

## Outcome (required)
What does done look like? Specific and verifiable.

## Notes
Open questions, alternatives considered, links to relevant vault notes
or other issues.
```

### Research issue

```markdown
## Question (required)
The specific question to answer.

## Why now (required)
What triggered this and why it's worth tokens.

## Deliverable (required)
What artifact lands when done — a vault note, a Linear comment with
findings, a follow-up issue, etc.

## Time budget
Soft cap on hours / dollars to spend before reporting back.
```

### Dev issue (v2)

```markdown
## Repo
owner/repo

## Goal (required)
What change in one sentence.

## Acceptance criteria (required)
- [ ] Tests pass
- [ ] (other measurable outcomes)

## Constraints
Any "must not change X" guardrails.
```

## Lifecycle ownership

Lifted from npc-simulation `/work` skill. The agent owns issue status for issues it's actively working on:

- **Pickup**: agent moves issue from `Todo → In Progress` when it begins. Auto-applied (logged as proposal).
- **Done**: agent moves `In Progress → Done` when the proposal that closes the issue is applied (or when the dev-PR merges, for v2). Auto-applied.
- **Stale revert**: a daily scheduled trigger checks for `In Progress` issues with no Linear activity in the configured window (default 7 days). The agent reverts to `Todo` and adds a comment noting the reason. Auto-applied.
- **Manual user changes** override the agent. If the user transitions an issue, the agent doesn't fight it.

The user should rarely need to touch issue status manually for agent-owned work. Strategic decisions (priority, labels, project assignment) remain user-gated through the `pm_agent`.

## Triage workflow

`pm_agent` runs on a daily schedule. For every issue in `Triage`:

1. Classify type label.
2. Classify subsystem labels (if dev-typed).
3. Suggest priority.
4. Suggest target state (`Backlog` for not-yet-actionable, `Todo` for ready).
5. Emit a **single proposal** for the whole batch (not one per issue) — user approves/rejects/edits collectively.

Triage proposals are user-gated. The user can approve all, approve with edits, or reject and re-triage.

## Issue creation discipline

When the agent creates an issue (any subagent, via `linear_agent`):

- Required: `title`, `type` label, body following the matching template, `Triage` state (unless agent has high confidence — see below).
- Issues land in `Triage` by default. The agent skips `Triage` only when:
  - The issue is auto-generated by an obvious trigger (user said "remind me to call mom" → `life-task`, `Todo`, priority 3, no triage needed)
  - All required fields are unambiguously fillable from context
- Source attribution: every agent-created issue includes a "Created by personal-assistant" footer with the wake-id and source (journal/inbox/SMS/observation).

## Dependencies

Use Linear's `blocks` / `blocked-by` relations directly. Authored by the agent via `tools/linear link <blocker> <blocked>` (added beyond what npc-simulation's CLI supports).

`tools/linear blocked` lists blocked issues; `tools/linear next` filters them out so the agent never picks up something that can't move.

## Cycles

Optional. v1 doesn't use cycles. If the user wants weekly reviews scoped to a cycle, the agent can adopt them — `pm_agent` adds an additional triage step to assign issues to the active cycle.

## Bulk operations

Mass labels, mass state changes, archives spanning >5 issues require a user-gated proposal. This is the backstop against an LLM mistake re-categorizing the entire backlog.
