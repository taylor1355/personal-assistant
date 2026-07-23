# tools/

Host-side developer tooling. The Linear CLI (`linear` + `linear-pm/`) is documented
in [../docs/LINEAR_CONVENTIONS.md](../docs/LINEAR_CONVENTIONS.md). The scripts below
support the `/work` orchestrator ([../.claude/skills/work/SKILL.md](../.claude/skills/work/SKILL.md)).

| Script | Purpose |
|---|---|
| `preflight_dispatch.sh` | Phase 0 gate: verifies the shared toolchain (git, gh, uv, node, go), Linear reachability, worktree bootstrap state, and that the unit suite runs. Exit 0 = green, 1 = red. Run before dispatching. |
| `setup_worktree.sh` | Bootstraps a fresh worktree to a test-runnable state: copies `.env` from a sibling worktree, `uv sync`s `agent/.venv`, and `npm install`s the Linear CLI deps. Idempotent. `--check` reports state without doing work. |
| `check_prs.sh` | Walks the FULL reviewer-comment history for one or more PRs and reports per-comment disposition (`[OPEN]` / `[DISPOSITIONED]`). No `--since` filtering, so "no OPEN entries" is a real signal, not a filter artifact. |
| `watch_pr_merges.sh` | Emits one `MERGED #<n> [<branch>] <title>` line per PR merge, for wrapping in the `Monitor` tool (Phase 6b merge watcher). |
| `check_pr_cascade.sh` (+ `.py`) | Given a just-merged PR and the open PR set, shortlists open PRs whose reviewer feedback references files the merge touched (cross-PR cascade). A shortlist generator — manual review is the gate. |
| `hermes_gateway_supervisor.py` | Crash-restart watchdog for the live Hermes gateway. Watches gateway liveness continuously and relaunches it on death, cause-agnostic. Stdlib-only; runs under pythonw. See "Gateway supervisor" below. |
| `install_hermes_supervisor.ps1` | Registers/unregisters/checks the supervisor as an at-logon task (or Startup-folder launcher). Run manually by the user as a separate approved step. |

`check_prs.sh`, `watch_pr_merges.sh`, and `check_pr_cascade.*` are ported from
npc-simulation; internal `NPC-xxx` references are original provenance (npc-simulation
issue ids documenting why the code is shaped that way, not personal-assistant ids).

## One-time prerequisites (merge watcher only)

`watch_pr_merges.sh` needs, once per machine:

```bash
gh extension install cli/gh-webhook     # event stream for PR merges
winget install jqlang.jq                # standalone jq (the webhook pipe uses it)
```

The other scripts use `gh`'s bundled jq and need no extra install. `check_pr_cascade.*`
uses the project's uv-managed Python when no standalone `python3` is present.

## Gateway supervisor

`hermes_gateway_supervisor.py` self-heals the live Hermes gateway. The gateway's
only launch mechanism is a Startup-folder shortcut that fires **only at login**,
so a mid-session crash leaves it down until the next logon (a 2026-06-30 crash
cost ~12h of downtime — PA-104). The supervisor closes that gap: it polls
gateway liveness continuously and relaunches on death, whatever the cause.

**What it does each cycle (default every 30s):**

1. Reads `HERMES_HOME\gateway.pid` for the recorded PID.
2. Resolves that PID to a live process (PowerShell CIM) and checks the command
   line — it matches both `python.exe` and `pythonw.exe` and keys on
   `hermes_cli` + `gateway run`, so PID reuse by an unrelated process reads as
   DEAD, not a false ALIVE. It never trusts `gateway_state.json` for liveness
   (that file is event-driven and goes stale while the gateway is healthy).
3. On death: relaunches `HERMES_HOME\gateway-service\Hermes_Gateway.cmd`
   detached (no console), with exponential backoff (5s → 15s → 60s → 300s) and
   a circuit breaker — after 5 restarts in 15 minutes it trips and cools down
   for 30 minutes rather than hot-looping a gateway that can't stay up.

**Install / uninstall / check** (run manually — see note below):

```powershell
# Register the at-logon scheduled task (default; no admin required):
powershell -ExecutionPolicy Bypass -File tools\install_hermes_supervisor.ps1

# Or drop a hidden-window launcher into the Startup folder instead:
powershell -ExecutionPolicy Bypass -File tools\install_hermes_supervisor.ps1 -Method Startup

# Report install state + resolved interpreter (read-only):
powershell -ExecutionPolicy Bypass -File tools\install_hermes_supervisor.ps1 -Check

# Remove the task and/or Startup launcher:
powershell -ExecutionPolicy Bypass -File tools\install_hermes_supervisor.ps1 -Uninstall
```

The installer resolves a `pythonw.exe` interpreter in priority order: `uv python
find`, then a `%APPDATA%\uv\python\cpython-3.11-*` install, then this repo's
`agent\.venv\Scripts\pythonw.exe`.

> **Installation is a separate, user-approved step.** Building or checking out
> the repo installs nothing; the `install_*.ps1` script only registers anything
> when you invoke it yourself (without `-Check`).

**Manual / dry runs:**

```bash
# One check-decide-act cycle, never launches (classify + decide + log only):
python tools/hermes_gateway_supervisor.py --dry-run --once

# One real cycle (will relaunch if the gateway is dead), then exit:
python tools/hermes_gateway_supervisor.py --once
```

**Configuration** — `HERMES_HOME` (env; falls back to
`C:\Users\taylor\Dev\hermes-home` with a warning) plus these tunables, each
overridable via env var:

| Env var | Default | Meaning |
|---|---|---|
| `SUPERVISOR_POLL_SECONDS` | 30 | Seconds between liveness checks. |
| `SUPERVISOR_STABILIZE_SECONDS` | 60 | A restart must hold this long to forgive prior failures. |
| `SUPERVISOR_CB_WINDOW_SECONDS` | 900 | Circuit-breaker window. |
| `SUPERVISOR_CB_MAX` | 5 | Max restarts in the window before tripping. |
| `SUPERVISOR_CB_COOLDOWN_SECONDS` | 1800 | Cooldown once tripped. |
| `SUPERVISOR_RESTART_GRACE_SECONDS` | 10 | Wait after launch before confirming a new process appeared. |

**Files it writes** (under `HERMES_HOME\logs\`):

- `supervisor.log` — rotating log (`supervisor: <verb> <subject>`).
- `supervisor.heartbeat.json` — liveness snapshot rewritten each cycle
  (`state`, `consecutive_failures`, `restarts_in_window`, `gateway_alive`, …).
- `supervisor.lock` — single-instance guard; a second supervisor exits if a live
  one already holds it.
