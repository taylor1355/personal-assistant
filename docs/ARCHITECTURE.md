# Architecture

Reference for the design of `personal-assistant`. The shape is considered stable; specific tools, subagents, and config keys evolve as work progresses.

Linked specs:
- [PROPOSAL_FORMAT.md](PROPOSAL_FORMAT.md) — proposal file schema
- [BUDGET.md](BUDGET.md) — token spend caps and self-throttling
- [LINEAR_CONVENTIONS.md](LINEAR_CONVENTIONS.md) — labels, priorities, states, issue templates
- [VAULT_ORGANIZATION.md](VAULT_ORGANIZATION.md) — Obsidian Bases views, frontmatter schemas, vault-organizer agent's playbook
- [DEVOPS.md](DEVOPS.md) — v2 capability: agent-authored PRs to user's repos

## Design principles

1. **Writes go through a proposal queue.** The agent never mutates user state directly. Structured proposals are emitted; a separate executor on the host applies them. Some Linear ops are auto-approved (still logged) — see "Approval gates" below.
2. **Agentic orchestration.** A root agent routes per-trigger to specialist subagents and tools. No fixed pipeline.
3. **Event-driven, debounced.** The agent sleeps and wakes on triggers. A host-side dispatcher batches events with a quiet-period / max-delay / max-buffer policy, then invokes the agent with the batch in context.
4. **Value-prioritized wake.** Every wake asks "what's the most valuable thing I can do right now?" Three tiers: time-sensitive obligations, advanceable user interests, long-horizon backburner. No idle/active distinction; just ranking.
5. **Token-budgeted.** Daily and weekly hard caps; soft target lower. Tier-1 work can exceed the soft cap; only hard caps block.
6. **Linear and Obsidian serve distinct purposes; no mirror.** Linear is the issue tracker; vault is knowledge + working notes. Each is first-class for its purpose.
7. **Configurable provider routing.** Model selection is a config concern; code paths are provider-agnostic except where a model-specific feature justifies a branch.
8. **Decoupled vault.** The agent works on its own copy of the vault inside its container. A sync daemon bridges that copy to the user's working vault.
9. **Reusable with opinionated defaults.** Onboarding a different user is config — not code.

## Capability tiers

The system grows in capability tiers. Each is shippable on its own; later tiers depend on earlier ones.

| Tier | Capability | Blocking dependencies |
|---|---|---|
| **v0** | Proposal loop end-to-end. Manual `wake` triggers a single subagent (`journal_agent`) that detects completed todos and emits proposals. | none — landed |
| **v1** | The "useful daily" version. Inbox + SMS as unified capture+command, debounced dispatcher, intake agent, value-prioritized root, Linear backbone, vault-organizer with Bases views, daily digest. | v0 |
| **v2** | Agent-authored dev work. Picks up code-typed Linear issues, works in worktrees, runs tests, submits PRs to allowed repos. | v1 |
| **v3+** | Open. Things that emerge from running v1+v2 — likely calendar/email writes, multi-repo dev, scheduled R&D programs. | v1, v2 |

## Components

Six services, three trust zones.

```
┌─ container (untrusted; read-only creds, network-isolated) ─────────┐
│  agent        Python + NeMo Agent Toolkit                          │
│                - root + subagents + tools                          │
│                - read-only: Gmail, Calendar, vault copy            │
│                - emits proposals; some Linear ops auto-applied     │
│                  via tools/linear (still logged as proposals)      │
│                - calls Anthropic / OpenRouter / Ollama per config  │
└────────────────────────────────────────────────────────────────────┘
                           │
                           │ (proposals: filesystem)
                           ▼
┌─ host (trusted; holds write credentials) ──────────────────────────┐
│  executor    Go     applies approved vault/calendar/email writes;  │
│                     records audit log of every applied proposal    │
│                                                                    │
│  dispatcher  Go     watches triggers (file-watch, cron, webhooks); │
│                     debounces per-source (quiet/max-delay/buffer); │
│                     invokes agent CLI with batched context         │
│                                                                    │
│  sms         Go     Twilio webhook in / REST out; behind           │
│                     Cloudflare Tunnel                              │
│                                                                    │
│  sync        Go     two-way sync: user vault ↔ agent's copy        │
│                                                                    │
│  devops      Go     v2: GitHub PR submission for dev-typed Linear  │
│                     issues; holds GITHUB_TOKEN; sandboxed by repo  │
│                     allowlist                                      │
└────────────────────────────────────────────────────────────────────┘
```

The agent container has no write credentials to GitHub, Gmail, Calendar, the user's real vault, or Twilio. Compromise of the agent corrupts its own scratchpad and consumes API tokens — nothing else.

## The proposal queue

The central invariant for irreversible mutation. See [PROPOSAL_FORMAT.md](PROPOSAL_FORMAT.md) for the file format and validation rules.

**Shape:** the agent writes a markdown file under `00 - Assistant/Proposals/YYYY-MM-DD-HHMM-<slug>.md` with frontmatter declaring `action`, `target`, and `status: pending`. The user reviews in Obsidian and approves by flipping `status` to `approved`. The executor watches the folder, validates, applies via the typed adapter, and transitions to `applied` or `failed`. Applied proposals are moved to `Proposals/Applied/YYYY-MM/`.

**Why markdown:** the user reviews in Obsidian directly. No extra UI, no extra database. The vault is the queue.

### Approval gates

Not every operation goes through user-approval. Some operations have low blast radius and clear undo (Linear status transitions, comments) so gating them is friction without safety benefit. Every action type is classified:

| Class | Examples | Path |
|---|---|---|
| **User-gated** (default) | `vault_edit`, `vault_create`, `vault_delete`, `calendar_*`, `email_*`, `linear_delete_issue`, `linear_transition_to_canceled`, `linear_bulk_op` (>5 issues) | proposal → user approves → executor applies |
| **Auto-applied** | `linear_create_issue`, `linear_update_issue`, `linear_transition_forward`, `linear_set_priority`, `linear_set_labels`, `linear_set_assignee`, `linear_add_comment`, `linear_link_blocker` | proposal → executor applies immediately → file lands in `Proposals/Applied/` (still auditable) |

Auto-applied proposals are still emitted as files so the user has a complete audit log of what the agent did. The user can disable auto-apply per-class in `config/user.yaml` if they want everything gated.

## Event-driven wakes

The agent sleeps between triggers. Triggers are debounced by a host-side dispatcher.

### Trigger types

| Trigger | Source | Default cadence |
|---|---|---|
| `inbox_edit` | file-watch on `00 - Assistant/Inbox.md` (and `Inbox/*.md` if used) | quiet 5 min, max delay 15 min, max 10 events |
| `sms_inbound` | Twilio webhook → sms service | quiet 1 min, max delay 5 min, max 5 messages |
| `email_batch` | scheduled poll of Gmail; only triggers if ≥1 new since last wake | every 30 min |
| `scheduled` | cron entries (morning brief, evening reconcile, dated-plan check) | per-job |
| `idle_pulse` | cron, periodic; triggers a value-prioritized wake even with no events | every 1 hr |

### Debounced dispatcher

The `dispatcher` service holds per-source state and fires when **any** condition trips:
- `now - last_event ≥ quiet_period`
- `now - pending_since ≥ max_delay`
- `buffer_size ≥ max_buffer`

All three are per-source, configurable in `config/user.yaml`. The dispatcher invokes `personal-assistant-agent wake --reason=<source> --payload <json>` with the batch.

### Value-prioritized wake model

Every wake the root agent ranks possible actions and picks the highest-value tier:

1. **Time-sensitive obligations** — SMS replies owed, imminent calendar items, todo completions to detect, urgent Linear issues approaching deadlines.
2. **Advanceable user interests** — top of Linear backlog (issues in `Todo`, ranked by priority), in-progress issues that can take a step forward, vault-organization opportunities (a folder needing frontmatter to enable Bases queries).
3. **Long-horizon backburner** — research projects, exploratory work, R&D efforts the user has filed.

Tier-1 work can run over the soft budget; only the daily/weekly hard cap blocks. Tier-2 and Tier-3 self-throttle. See [BUDGET.md](BUDGET.md).

### Session logs

Each wake writes to `00 - Assistant/Sessions/YYYY-MM/YYYY-MM-DD-HHMM.md`: trigger, batched events, planning summary, subagents invoked, proposals emitted, Linear ops performed, "recommended first action" for next session. Modeled on the `claude_partner` pattern.

## Agent shape

Root agent dispatching to specialist subagents. NeMo Agent Toolkit is the framework; routing is dynamic per-trigger and per-context.

### Subagents

| Subagent | Reads | Emits | Triggers it serves |
|---|---|---|---|
| `intake_agent` | inbox / SMS content | classifies into journal/todo/plan/calendar/research_request/instruction; routes to other subagents OR emits proposals directly | `inbox_edit`, `sms_inbound` |
| `journal_agent` | today's journal section, todos | proposals to mark todos done | scheduled, on-demand from intake |
| `calendar_agent` | Google Calendar (read-only) | proposals to create events, conflict warnings, dated-plan reminders | `email_batch`, scheduled |
| `email_agent` | Gmail (read-only) | proposals to draft replies, label, archive | `email_batch` |
| `vault_organizer` | full vault | proposals to add frontmatter, create Bases views, restructure folders, write MOCs | scheduled, idle pulses |
| `research_agent` | web (via search tool) + Linear backlog | proposals to write/extend research notes; updates issue status | tier-2/3 wakes when research issues are top-ranked |
| `reading_agent` | Goodreads API + vault literature notes | proposals to update reading list, draft notes | scheduled |
| `linear_agent` | Linear (read+write) | tactical Linear ops (status transitions, label updates) — used by other subagents, not user-facing | invoked by other subagents |
| `pm_agent` | Linear backlog + recent activity | strategic proposals: triage Triage state, label/prioritize, create issues for newly-discovered work | scheduled (daily triage) |
| `devops_agent` (v2) | repo, Linear issue, code | git worktree, code, tests, PR | tier-2 wake when a code-typed issue is top-ranked |

### Shared tools

| Tool | Purpose |
|---|---|
| `vault_read` | UTF-8 read under the vault root with traversal protection |
| `proposal_enqueue` | write a structured proposal file |
| `linear_cli` | wrapper around `tools/linear` (TS-based, lifted from npc-simulation): list/get/create/update/transition/link |
| `web_search` | for research_agent |
| `sms_send` | enqueue outbound SMS via the sms service |
| `memory_query` | scored retrieval over agent's session logs and knowledge files (similarity + importance + recency) |

## Provider routing

A provider abstraction speaks the OpenAI API surface. Routes by task class, configured in `config/providers.yaml`. Native SDKs (Anthropic, Google) are used only when a model-specific feature justifies the branch — prompt caching, extended thinking, long-context, native tool use.

```yaml
routing:
  default: cloud-strong
  overrides:
    intake_agent: cloud-fast      # high-frequency, lighter task
    research_agent: cloud-strong  # quality matters
    vault_organizer: local-strong # bulk frontmatter work; cheap and private
    pm_agent: cloud-strong        # strategic decisions

providers:
  cloud-strong:  { kind: anthropic, model: claude-opus-4-7 }
  cloud-fast:    { kind: openai_compat, base_url: https://openrouter.ai/api/v1, model: anthropic/claude-haiku-4-5 }
  local-strong:  { kind: openai_compat, base_url: http://host.docker.internal:11434/v1, model: qwen2.5:32b-instruct-q5_K_M }
  local-fast:    { kind: openai_compat, base_url: http://host.docker.internal:11434/v1, model: llama3.1:8b }
```

Hardware target (RTX 4090, 24GB) supports Qwen 32B at Q4-Q5 for `local-strong` and 7-8B FP16 for `local-fast`. The router does not load models; it relies on Ollama's swap.

## Vault handling

**Two copies, one-way reads + bidirectional writes scoped to `00 - Assistant/`:**

- User's working vault — canonical. The agent and executor never mutate content outside `00 - Assistant/` without going through a user-approved proposal.
- Agent's vault copy in the container — full read; writes are scoped to `00 - Assistant/` (sessions, knowledge, digest, proposals). The executor (host-side) is what writes to the real vault.

The `sync` service reconciles between them with debounced two-way sync. Conflicts within `00 - Assistant/` resolve by timestamp with a dated backup. In practice, the proposal-queue pattern means conflicts are rare.

### Vault organization is first-class work

The vault's lack of frontmatter, tags, and structured properties is a weakness the user actively wants fixed. The `vault_organizer` subagent treats this as ongoing work: incremental proposals to add frontmatter to existing notes, create Bases views (`.base` files) for natural queries, write MOCs (Maps of Content), and propose folder restructuring. Bases is Obsidian's native (since 1.9) frontmatter-driven view system; once notes carry properties, Bases gives the user organizational dashboards over their own content. Full schema and view library in [VAULT_ORGANIZATION.md](VAULT_ORGANIZATION.md).

This is distinct from issue tracking — Linear handles tasks/issues; the vault is knowledge and working notes. The two do not mirror each other.

## Linear integration

Linear is the issue tracker for everything: life tasks, R&D backlog, dev work. Conventions in [LINEAR_CONVENTIONS.md](LINEAR_CONVENTIONS.md). The agent works through `tools/linear` (bash + TS, lifted from npc-simulation with `link`/`unlink` added).

### Two-layer agent pattern

- **`linear_agent`** is the tactical interface — executes ops, no judgment. Other subagents call it.
- **`pm_agent`** is strategic — proposes triage decisions, label changes, priority adjustments, issue creation from observed work. Operates on its own schedule (daily triage).

This naturally implements the auto-approve-mechanical / gate-strategic split: tactical lifecycle ops (`linear_agent`'s domain) are auto-applied; strategic decisions (`pm_agent`'s output) flow through the proposal queue.

### Issue ownership lifecycle

Lifted from npc-simulation's `/work` skill: when the agent picks up an issue, it auto-transitions `Todo → In Progress`. On completion (proposal applied OR PR merged for dev work), it auto-transitions `In Progress → Done`. Stale `In Progress` issues (no movement in N days) auto-revert to `Todo` so the backlog stays accurate. All three are auto-approved.

### No mirror in vault

Linear has its own UI; the vault does not reproduce issue lists. The agent reads Linear via `tools/linear` whenever it needs current state; the vault's role is knowledge + working notes (`00 - Assistant/Sessions/`, `00 - Assistant/Knowledge/`, project notes in `03 - Personal Projects/`).

## Inbox + SMS as unified capture+command

The user has one input surface: the inbox note (and its SMS bridge). No formatting required; no command syntax. Free-form text. The `intake_agent` classifies each chunk:

- `journal_entry` → routed to journal_agent for incorporation
- `todo` → proposal to add to short-term todos
- `plan` → proposal to create dated plan file
- `calendar_item` → proposal to create event
- `research_request` → Linear issue created (auto-applied) and possibly picked up
- `organization_instruction` → routed to vault_organizer
- `question_to_agent` → response sent (vault note or SMS reply)
- `direct_command` → executed (e.g., "remind me at 3pm")
- `noise` → archived to `00 - Assistant/Raw/` for posterity, no action

If the user formats in-inbox (e.g., explicit headers, todo bullets), the intake_agent respects the formatting rather than re-parsing.

## Security model

- Container holds only read-only creds: Gmail `gmail.readonly`, Calendar `calendar.readonly`, Linear `LINEAR_API_KEY` (Linear's API has no granular scopes; the team key constrains targeting to the personal-assistant team).
- `executor`, `sms`, `dispatcher`, `sync`, `devops` services live on the host. Each has only the credentials it needs.
- Proposals are validated against typed schemas before applying. Unknown action types are rejected.
- Every applied proposal appends an audit entry with before/after content hashes (or, for non-vault actions, payloads) to `var/executor/audit.log`.
- v2 `devops` service is constrained by `GITHUB_ALLOWED_REPOS`; PRs are submitted, not direct pushes.
- Compromise scenarios enumerated in [SECURITY.md](SECURITY.md) (TBD).

## Reusability

Onboarding a different user is configuration only:

- `config/user.yaml` — vault path, timezone, phone, Google account, trigger schedules, subagent enable/disable
- `config/providers.yaml` — provider routing
- `.env` — API keys, OAuth refresh tokens, Twilio creds, Linear API key

No code changes for: switching vaults, switching phones, enabling/disabling subagents, routing to different LLM providers, pointing at a different Linear team, allowlisting different GitHub repos.

A later one-time setup script will cover OAuth dances, Twilio number provisioning, and Linear team auto-creation. Not in v1.

## Prior art

- **`claude_partner` pattern** (`taylor1355/npc-simulation`) — topical knowledge files, session logs, scope-based autonomy. The assistant's self-management surface (`00 - Assistant/Knowledge/`, `Sessions/`) is modeled on it.
- **`productivity_tools` proposal pattern** (`taylor1355/npc`) — `suggest_actions` → reviewable `InboxAction` → `execute_actions`. The proposal queue is the same pattern at process scope.
- **`mind` cognitive architecture** (`taylor1355/npc`) — LangGraph-over-Pydantic pipeline; per-node tokens/latency telemetry via `merge_dicts` reducer; scored memory retrieval; safe validation-failure fallback. Memory scoring and telemetry transfer; the fixed-DAG shape does not.
- **`tools/linear` + PM/work skills** (`taylor1355/npc-simulation`) — bash + TS CLI using `@linear/sdk`; two-layer agent pattern (`linear` tactical, `product-manager` strategic); auto-approved lifecycle transitions in `/work`. Lifted with adaptations.
