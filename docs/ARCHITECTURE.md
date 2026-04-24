# Architecture

This document describes the design of `personal-assistant`. It is a reference for the repo's author and anyone forking the project. The shape is considered stable; specific tools, subagents, and config keys will change as the MVP is built.

## Design principles

1. **Writes go through a proposal queue.** The agent never mutates vault files, calendar entries, emails, or any external state directly. It emits structured proposals; a separate process, outside the agent's container, applies them only after the user approves.
2. **Agentic orchestration.** A root agent routes to subagents and tools per request. No fixed DAG — the same trigger may invoke different subagents depending on context.
3. **Event-driven, not polling.** The agent is a daemon that sleeps and wakes only on specific triggers. Each wake runs to completion with its trigger in context, then sleeps again.
4. **Obsidian is the primary interface.** The vault is the assistant's inbox, scratchpad, and output surface. SMS is secondary.
5. **Configurable provider routing.** Model selection is a config concern; the code path is provider-agnostic wherever a model-specific feature isn't needed.
6. **Decoupled vault.** The agent works on its own copy of the vault inside its container. A sync daemon bridges that copy to the user's working vault.
7. **Reusable with opinionated defaults.** Onboarding a different user is a config change — paths, accounts, phone, provider mix — not a code change.

## Components

Four services, running in three trust zones.

```
┌─ container (untrusted; read-only creds, network-isolated) ─────────┐
│  agent        Python + NeMo Agent Toolkit                          │
│                - root agent + subagents + tools                    │
│                - read-only: Gmail, Calendar, vault (agent copy)    │
│                - emits proposals, never mutates anything           │
│                - calls local Ollama + cloud LLM APIs               │
└────────────────────────────────────────────────────────────────────┘
                           │
                           │ (proposals: filesystem or localhost HTTP)
                           ▼
┌─ host (trusted; holds write credentials) ──────────────────────────┐
│  executor    Go                                                    │
│                - reads approved proposals                          │
│                - validates + applies (vault / calendar / email)    │
│                - audit log                                         │
│                                                                    │
│  sms         Go                                                    │
│                - Twilio webhook in / REST out                      │
│                - forwards inbound to agent, delivers outbound      │
│                - behind Cloudflare Tunnel                          │
│                                                                    │
│  sync        Go                                                    │
│                - two-way sync: user vault ↔ container-mounted copy │
│                - debounced; conflict-aware                         │
└────────────────────────────────────────────────────────────────────┘
```

The agent container has no write credentials to anything. Compromise of the agent can corrupt its own scratchpad but cannot send email, mutate calendar, or write to the user's real vault.

## The proposal queue

The central invariant. Every write flows through it.

**Proposal format:** a markdown file in `<agent-vault>/00 - Assistant/Proposals/YYYY-MM-DD-HHMM-<slug>.md`, with frontmatter:

```yaml
---
proposed_at: 2026-04-24T09:15:00-04:00
agent: journal_agent
action: vault_edit
target: 02 - Todos/01 - Short Term Todos.md
status: pending   # pending | approved | rejected | applied | failed
---
```

Body: a human-readable description of the proposed change, the diff preview, and any reasoning. The user approves by editing the frontmatter (`status: approved`) or checking a box — the exact approval mechanism is TBD but will be one round-trip in Obsidian.

**Executor loop:** watches the proposals folder; when a file transitions to `approved`, validates (schema check, target-file existence, diff applies cleanly), executes via the typed adapter for `action`, and transitions to `applied` or `failed` with a result block appended. Applied proposals are moved to `00 - Assistant/Proposals/Applied/YYYY-MM/` monthly.

**Why markdown files instead of a queue service:** the user reviews them in Obsidian directly. No separate UI, no separate database, no round-trip through another tool. The vault is the queue.

## Event-driven wakes

The agent sleeps between triggers. Trigger types:

| Trigger | Source | Cadence |
|---|---|---|
| inbox edit | file-watcher on `00 - Assistant/Inbox.md` (or `/Inbox/*.md`) | immediate debounced |
| email batch | scheduled poll that wakes the agent only if ≥1 new email | ~30 min |
| sms inbound | Twilio webhook → sms service → agent | immediate |
| scheduled | cron-like: morning brief, end-of-day reconciliation, dated-plan check | per-job |

Each wake receives the trigger event in context. The agent plans, possibly invokes subagents, emits proposals, possibly sends SMS, writes a session log, and exits. No long-running main loop.

**Session logs** go to `00 - Assistant/Sessions/YYYY-MM/YYYY-MM-DD-HHMM.md`, following the `claude_partner` pattern (see "prior art" below): what was the trigger, what the agent did, what proposals were emitted, "recommended first action" for next time if relevant.

## Agent shape

Root agent + dispatchable subagents + shared tools, running on NeMo Agent Toolkit.

**Root agent** receives the trigger and decides which subagents/tools to invoke. It does not do domain work itself.

**Subagents** (planned, in rough priority order):

- `journal_agent` — reads today's journal, detects completed todos, proposes edits
- `calendar_agent` — reads Calendar, detects conflicts, proposes events, powers dated-plan reminders
- `email_agent` — reads Gmail, summarizes, triages, proposes replies / labels
- `vault_organizer` — proposes frontmatter, tags, MOCs, link structure; incremental vault improvement
- `research_agent` — multi-step web research on a topic
- `reading_agent` — Goodreads ↔ vault sync

**Shared tools** (planned):

- `vault_read` — read any file in the agent's vault copy
- `proposal_enqueue` — write a proposal file
- `memory_query` — retrieve from scored memory (similarity + importance + recency, per the `mind` project's pattern)
- `web_search` — for research
- `sms_send` — enqueue an outbound SMS (the sms service delivers)

## Provider routing

A single provider abstraction speaks the OpenAI API surface. It routes by task class, configured in `config/providers.yaml`:

```yaml
default: local-fast
overrides:
  research_agent: cloud-strong
  vault_organizer: local-strong
  root: cloud-fast

providers:
  local-fast:   { base_url: "http://ollama:11434/v1", model: "llama3.1:8b" }
  local-strong: { base_url: "http://ollama:11434/v1", model: "qwen2.5:32b-instruct-q5_K_M" }
  cloud-fast:   { base_url: "https://openrouter.ai/api/v1", model: "..." }
  cloud-strong: { native: "anthropic", model: "claude-opus-4-7" }
```

Native SDKs (Anthropic, Google) are used only when a model-specific feature justifies the branch — prompt caching, extended thinking, long-context modes. Everything else goes through OpenAI-compat.

A **target GPU** of 24GB (RTX 4090) means practical local options include Qwen 32B at Q4-Q5 for complex routing and 7-8B class at FP16 for fast tasks. The router does not load models; it relies on Ollama's model swap.

## Vault handling

**Two copies:**

- User's working vault — canonical. The agent never touches it directly.
- Agent's vault copy — lives in the container. Full read + write, but only for the `00 - Assistant/` subtree.

The `sync` service maintains a two-way sync of `00 - Assistant/` and a read-only copy of everything else:

- User's edits outside `00 - Assistant/` → agent's copy (the agent sees them read-only).
- User's edits inside `00 - Assistant/` → agent's copy (this is how approvals and inbox edits reach the agent).
- Agent's writes to `00 - Assistant/` → user's vault (via the executor; the sync daemon carries them back).
- Executor writes outside `00 - Assistant/` (e.g., appending to the current year's journal, editing the todos file) → user's vault directly; sync picks them up on the next cycle.

Conflicts are resolved by timestamp with a dated backup of the losing side. In practice, the proposal-queue pattern means the agent and user rarely edit the same file at the same time.

**Respecting the vault's shape.** Most of the user's notes carry no frontmatter or tags; metadata lives in folder and filename conventions (PARA-like numbered folders, year-collated journals, `YYYY-MM-DD <slug>.md` plan files, category-bulleted todo files). When the assistant writes NEW content, it follows those conventions. When it IMPROVES organization — adding frontmatter, tags, MOCs — it does so through the proposal queue so the user drives the migration.

## Security model

- Container has only read-only credentials (Gmail `gmail.readonly`, Calendar `calendar.readonly`, vault read-only mount outside `00 - Assistant/`).
- Executor holds write credentials in `.env` on the host. Not mounted into the container.
- SMS service holds Twilio credentials.
- Google OAuth tokens and API keys rotate via standard refresh flows; refresh tokens are encrypted at rest.
- Executor validates every proposal against a typed schema before applying. Unknown `action` types are rejected.
- Every applied proposal appends an audit entry with before/after content hashes.
- Compromise scenarios and their blast radius are enumerated in `docs/SECURITY.md` (TBD).

## Reusability

Onboarding a different user is a config change:

- `config/user.yaml` — vault path, timezone, phone, Google account email, trigger schedules, subagent enable/disable, assistant vocabulary (greeting, style)
- `config/providers.yaml` — provider routing
- `.env` — API keys, OAuth refresh tokens, Twilio creds

No code changes required for: switching vaults, switching phones, enabling/disabling subagents, routing to different LLM providers.

A later onboarding flow — a one-time setup script or UI — could cover the Google OAuth dance and Twilio number provisioning. That is not in the MVP.

## v0 scope

Ship the proposal loop end-to-end on one task, then iterate.

**Target task:** todo-completion detection.

**Components:**

- `agent`: NeMo root agent + `journal_agent` subagent + `proposal_enqueue` tool. Anthropic native provider only. Triggered manually: `docker compose run agent wake --reason=manual-test`.
- `executor`: Go service, polls `<agent-vault>/00 - Assistant/Proposals/`, applies approved vault edits.
- `sync`: minimal Go daemon, one-shot on startup + file-watch on `00 - Assistant/`.
- `compose.yml`: agent + Ollama (not used in v0 but wired) + local volumes.

**Not in v0:** Gmail / Calendar read, OpenRouter / local provider routing, Twilio, scheduled triggers, inbox file-watcher.

**Once v0 works end-to-end, the progression is:**

- v0.1 — inbox file-watcher as a second trigger
- v0.2 — scheduled triggers + dated-plan reminders (adds Calendar read)
- v0.3 — OpenAI-compat provider router + Ollama
- v0.4 — Goodreads sync
- v0.5 — Twilio
- v0.6 — email triage (adds Gmail read)
- v1 — vault_organizer subagent

## Prior art

Three pieces of the author's earlier work inform this design:

- **`claude_partner` pattern** (from `taylor1355/npc-simulation`) — topical knowledge files, session logs, scope-based autonomy. The assistant's self-management surface (`00 - Assistant/Knowledge/`, `00 - Assistant/Sessions/`) is modeled on it.
- **`productivity_tools` proposal pattern** (from `taylor1355/npc`) — `suggest_actions` → reviewable `InboxAction` objects with status + `is_modified` tracking → `execute_actions`. The proposal queue is the same pattern at the process level.
- **`mind` cognitive architecture** (from `taylor1355/npc`) — LangGraph-over-Pydantic pipeline with `merge_dicts` reducer for per-node telemetry, scored memory retrieval (`similarity + importance + recency`), validation-failure fallback. The memory scoring and telemetry patterns transfer directly; the fixed-DAG shape does not — this project is agentic rather than pipelined.
