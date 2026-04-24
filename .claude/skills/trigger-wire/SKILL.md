---
name: trigger-wire
description: Wire a new wake trigger (inbox watcher, cron entry, webhook) end-to-end — trigger source, agent-side handler, config, tests.
argument-hint: "[trigger name] [source kind: file-watch | cron | webhook]"
---

# Trigger Wire

You are wiring a new wake trigger into the personal-assistant system. Triggers are the only way the agent runs — the agent sleeps and wakes on specific events (see `docs/ARCHITECTURE.md#event-driven-wakes`). Every trigger has three pieces that must be consistent: a source, an agent handler, and a config entry.

**Scope check**: this skill is for *adding a new trigger to the repo during development*. It does not fire triggers at runtime.

## Inputs

- **Name** — snake_case (e.g., `inbox_edit`, `morning_brief`, `sms_inbound`).
- **Source kind** — one of:
  - `file-watch` — file or directory watcher (use `watchfiles` in Python; `fsnotify` in Go if host-side)
  - `cron` — scheduled, runs at fixed times
  - `webhook` — external HTTP event (Twilio, GitHub, etc.), received by a host-side service that invokes the agent
- **Description** — one sentence: what condition wakes the agent, what the handler does.

If any are missing, interview the caller.

## Procedure

### 1. Confirm the trigger belongs

Read `docs/ARCHITECTURE.md#event-driven-wakes`. Either the trigger is listed in the table (planned) or this is a deliberate addition. If new, propose the addition to ARCHITECTURE.md first and show the diff.

### 2. Implement the source

Depending on the source kind:

- **file-watch**:
  - Source lives in the **agent container** if watching paths inside `/data/`, or on the **host** (in a small Go helper) if watching the real vault.
  - Debounce appropriately (file systems emit multiple events per logical change).
  - On event, invoke the agent: `personal-assistant-agent wake --reason=<name> --payload <json>`.

- **cron**:
  - Source is a host-side cron job or systemd timer. Do NOT put cron inside the agent container.
  - The command invoked is the same CLI wake. Payload includes the scheduled time.

- **webhook**:
  - Source is a host-side HTTP handler (Go, in `sms/` or a dedicated service). The handler validates the incoming request (signature check for Twilio; HMAC for GitHub) and invokes the agent CLI with the parsed payload.

Add the source under the appropriate directory:
- file-watch (container-side): `agent/src/personal_assistant_agent/triggers/<name>.py`
- file-watch (host-side): `sync/internal/triggers/<name>.go` (or a new service if not sync-adjacent)
- cron: document the cron line; if shipped as part of the repo, put in `scripts/cron/<name>.cron`
- webhook: handler in the relevant Go service under `internal/webhooks/<name>.go`

### 3. Implement the agent-side handler

The root agent must know what to do when this trigger fires. Update:

- `agent/src/personal_assistant_agent/cli.py` — ensure `wake --reason=<name>` is accepted and routes to the right subagent(s). Do NOT embed domain logic here; just dispatch.
- `agent/src/personal_assistant_agent/agents/root.py` (when it exists) — add the trigger → subagent mapping.

### 4. Add config

- `config/user.yaml.example` — add the trigger under `triggers:` with any user-tunable parameters (enable/disable, schedule, debounce, webhook path).
- If the trigger needs secrets, add placeholders to `.env.example`.

### 5. Add tests

At minimum:
- Handler test: invoke `wake --reason=<name>` with a representative payload and verify the expected subagent(s) get dispatched and that output is a proposal file (not a direct mutation).
- Source test (for file-watch and webhook): simulate the source event and verify the CLI is invoked with the correct arguments. Mock subprocess boundaries.

For cron: no source test, but document the exact cron expression + timezone assumptions in a comment.

### 6. Update ARCHITECTURE.md

Move the trigger from "planned" to "shipped" in the event-driven-wakes table, noting its source kind and cadence.

### 7. Report

Summarize: name, source kind, files added/modified, subagents dispatched, config keys added, tests written. Flag anything still needed (secret provisioning, deploy-time cron install, tunnel setup for webhook).

## Discipline

- **Triggers are thin.** The source's only job is to decide "the agent should run now" and invoke the CLI. It does not read mail, look at the calendar, or decide which subagent to route to — that's the root agent's job.
- **Every wake must terminate.** The agent handler runs to completion and exits. If the handler wants to wait for a response, do it via a new trigger, not by keeping the wake alive.
- **No trigger poll loops in the agent container.** All polling lives in host-side sources. The agent process starts, handles, exits.
- **Secrets never in the container.** Webhook signature keys, OAuth refresh tokens, Twilio tokens stay on the host with the source service that needs them.
- **Idempotency matters.** If a webhook retries or a file watcher double-fires, the agent may wake twice for the same event. The handler (or the subagent) should tolerate duplicate invocations.
