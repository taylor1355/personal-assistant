# v1 Plan & Handoff (2026-06-24)

How to pick up the personal-assistant build after the v0 MVP. Pair this with the
auto-memory files `project-pivot-hermes-mvp` and `reference-hermes-local-setup` —
together they are the full picture. The pivot also re-triaged the Linear backlog
(team PA); see `tools/linear`.

## Where v0 landed (working today)

A self-hosted assistant on the user's Windows desktop:

- **Harness:** [Hermes Agent](https://github.com/nousresearch/hermes-agent) (local), cloned at `C:\Users\taylor\Dev\hermes-agent`. The gateway auto-starts at login (real Startup item → `C:\Users\taylor\Dev\hermes-home\gateway-service\Hermes_Gateway.cmd`).
- **Model:** `qwen3.6:27b` on Ollama (fully local). `gpt-oss:20b` was the spike model (too weak at multi-tool skills); full benchmark = **PA-23**.
- **Interface:** Telegram bot `@PersonalAssistant1355_bot`, two-way chat, locked to Taylor's chat id `8625635323`.
- **Value layer:** the `pa-tools` MCP server (`pa_mcp/pa_tools_server.py`) — 14 tools: `vault_read/list`, `linear_board/todo/next/issue/search` + `linear_create/comment/set_state/set_priority/link`, `today`, `assistant_write` (scoped to `00 - Assistant/`). Reuses the existing `read_vault_file` + `LinearClient` (no NeMo dep).
- **Lockdown:** `platform_toolsets` gives the agent only `mcp-pa-tools, skills, memory(, messaging)` — **no `terminal`/`file`**, so it cannot mutate user state outside the typed tools. The proposal-queue invariant, enforced by construction.
- **Skills:** `daily-briefing` (7am `hermes cron`, delivered to Telegram + archived to `00 - Assistant/Briefings/`) and `plan-work` (drafts a sequenced plan to `00 - Assistant/Plans/`; creates Linear issues only on explicit confirm). Both in `pa_mcp/skills/`, loaded via `skills.external_dirs`.
- **HERMES_HOME:** `C:\Users\taylor\Dev\hermes-home` (migrated out of Claude's package cache). **`PA_REPO_ROOT` (runtime)** = `C:\Users\taylor\Dev\personal-assistant` (main checkout — warm `tools/linear-pm/node_modules` + `.env`).

Branch `claude/modest-goldberg-361b61` — 5 commits (MCP server, briefing+tools, plan-work, Linear node-direct fix, briefing→chat). **No PR opened yet.**

### Loose ends
- **Reboot-test** the gateway auto-start (the one thing untested headless).
- **PA-23** model benchmark (qwen3.6 vs hermes4.3:36b; latency at the chosen context).
- `linear_cli.py` node-direct fix is committed on the branch **and** sits in `main`'s working tree (reconciles on merge).
- `docs/ARCHITECTURE.md` etc. still describe the pre-pivot NeMo/Go design — a docs-alignment pass is owed.

## v1 goal

Cross from read-mostly → **first real writes**, via the proposal→apply path, then Google reads, then the headline feature: **Gmail inbox sorting**.

## v1 architecture — the proposal / apply path (keystone)

The lockdown means the orchestrator literally cannot write user state. v1 adds the *approved-write* path without ever handing the LLM write creds:

1. **`propose` tool** (new pa-tools tool): the agent emits a structured proposal — reuse the existing `Proposal` Pydantic model (`agent/src/personal_assistant_agent/models.py`, `Action` enum) + `docs/PROPOSAL_FORMAT.md`. Writes the proposal to `00 - Proposals/` — a top-level vault folder *outside* `00 - Assistant/`, so `assistant_write` cannot reach it; only this typed tool (always `status: pending`) writes the queue, and only the user writes `status: approved`. Access-controlled, not honor-code.
2. **The applier (PA-3)** — the old Go executor, reborn as a deterministic, non-LLM `apply_proposals.py`: reads *approved* proposals, re-validates against the closed schema, applies via typed adapters (`vault_edit/create`, `gmail_modify`, `calendar_create`), transitions to applied/failed, audit-logs. **It holds the write creds; the orchestrator never does.** That's the trust boundary — credential separation in one process.
3. **Approval UX** — recommended: **Telegram** (the bot presents the proposal; user replies approve/reject). Alternative: flip a `status:` field in the proposal frontmatter from Obsidian. Decide early.

## v1 build sequence

1. **`propose` tool + proposal queue** — wire the `Proposal` schema; agent writes to `00 - Proposals/` (outside the agent's writable area). Validate the closed schema. ✅ done
2. **Applier** (`personal_assistant_agent/applier.py`, `apply-proposals` entry point) + adapters (`vault_edit` replace, `vault_create`, `vault_move`) + audit log + `Applied/` archive. Full **propose → approve → apply** loop proven. ✅ done
3. **Approval flow** — settled as the Obsidian **status-flip** (interim; eventual phone/web app per `project-approval-ux` memory). The applier runs as an **OS scheduled task** (`scripts/install_applier_task.ps1`), sweeping the queue on an interval — a host-side process separate from the Hermes gateway, so the agent never holds write creds.
4. **Google reads (PA-14)** — ⚠️ a bare "API key" cannot read private Gmail/Calendar; this needs **OAuth2** (Google Cloud project + OAuth client + one-time consent → refresh token in `HERMES_HOME/.env` or a creds file), read-only scopes. Add `gmail_read` + `calendar_read` tools (custom, or a Google MCP server).
5. **Inbox sorting (headline)** — classify inbox → `propose` Gmail label/archive changes → apply on approval (`gmail_modify` adapter). Replaces InboxZero. Start read-mostly (classify + surface in the briefing), graduate to apply.
6. **Fold calendar + email into the daily briefing** — now it covers "all modalities" (the original want).

## Open decisions
- ~~**Approval UX:**~~ settled: Obsidian status-flip now, phone/web app later.
- ~~**Applier trigger:**~~ settled: interval sweep via OS scheduled task.
- ~~**Applier process:**~~ settled: standalone (`apply-proposals`), holds creds, separate from the gateway.
- **Google auth:** confirm OAuth2 (not a bare API key); scopes (`gmail.modify` for sorting, `calendar.readonly`). Email/inbox deprioritized — `calendar.readonly` first.

## Linear issues (post-pivot)
**PA-3** in-process applier (keystone) · **PA-14** Calendar+Gmail read · **PA-9** vault intake → propose · **PA-11** Linear audit · **PA-5** pm/triage subagent · **PA-23** model benchmark. (PA-4/6/8/21 were canceled.)

## How to pick up next session
1. Read memory: `project-pivot-hermes-mvp`, `reference-hermes-local-setup` (all the operational gotchas: HERMES_HOME, node-direct Linear, gateway restart steps).
2. The gateway should be running (or auto-started at login) — text the bot to check. To restart manually: stop the python gateway process(es), then
   ```bash
   export HERMES_HOME="C:/Users/taylor/Dev/hermes-home"
   cd "C:/Users/taylor/Dev/hermes-agent" && .venv/Scripts/hermes.exe gateway   # run in background
   ```
3. Begin with build step 1 (the `propose` tool) — everything downstream depends on the proposal queue.
