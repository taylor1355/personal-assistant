# Personal Assistant — Roadmap

Living build plan, sequenced by leverage + dependency. Supersedes the sequencing
in [V1_PLAN.md](V1_PLAN.md) (the v1 write-path is done). Authored 2026-06-29
after a full design examination; design rationale lives in the auto-memory files
`project-productivity-system`, `project-assistant-capabilities`,
`project-todos-in-linear`, `project-approval-ux`.

## Where we are (live today)

- **v0:** local Hermes + `qwen3.6` orchestrator, Telegram bot, read-loop over vault + Linear, 7am daily-briefing cron.
- **v1 write path (PA-3):** `propose` → approve (Obsidian status-flip) → applier (`vault_edit` replace / `vault_create` / `vault_move`), scheduled every 10 min. **Live.**
- **Calendar (PA-14):** read-only Google Calendar, folded into the briefing. **Live.**
- **Life-task system:** ~65 SMART issues in the Linear **Personal** project (the mega-intake), with epics/sub-issues, GTD context labels, estimates, due dates.

## Design principles (from the 2026-06-29 examination)

1. **Capture without maintenance rots** — the vault proved it. Build the *loops* (review, capture, nudge), not just storage.
2. **Decouple** — journal / retro / habits / focus each stand alone; one lapse must not cascade (that's what killed the old process).
3. **Invert the ratio** — the assistant does the toil (scan, draft, prep just-in-time, conditioned on memory); Taylor makes small high-agency calls.
4. **Personal ≠ dev** — the briefing is personal; dev gets its own.
5. **Agentic production loops, not one-shot prompts**; **fix the source, not the symptom** (refactor the vault rather than warn around it).
6. **A good assistant nags** — persistent, calibrated follow-up to completion.

## Phases

### Phase 0 — Housekeeping (now)
- Merge the calendar PR (#5) if still open.
- **PA-30** — briefing personal/dev filter. Small; unblocks a clean personal briefing.

### Phase 1 — The core loop (the assistant's "OS") ← highest leverage
The daily/weekly/capture loop + the substrate they share. This is the anti-rot operating system; everything else enriches it.
- **PA-102** — memory / situational-awareness substrate + completion detection *(foundation — stops stale items, enables continuity)*
- **PA-100** — calibrated nudge engine *(persistent follow-up)*
- **PA-101** — low-friction daily capture *(evening prompt → journal; feeds the review)*
- **PA-96** — daily briefing v2: personal-first, synthesized, capacity-aware *(needs PA-30, PA-102)*
- **PA-99** — weekly review system *(anti-rot keystone; needs PA-100 + PA-101; outputs the weekly focus PA-96 consumes)*

### Phase 2 — Frictionless intake at scale
New tasks flow in without manual effort.
- **PA-93** — SMART tooling (due/estimate/parent/project) so the local agent can create well-formed issues
- **PA-1** — intake skill: bot-as-inbox *(in progress; needs PA-93)*
- **PA-5** — pm/triage subagent

### Phase 3 — Knowledge & vault foundation (compounding)
- **PA-97** — refactor vault todos: reconcile with Linear, archive stale *(High; first concrete vault step)*
- **PA-18** frontmatter schemas · **PA-20** vault overhaul · **PA-10** vault organizer
- **PA-98** — semantic knowledge layer: entity notes + hybrid retrieval *(rides PA-18/PA-10)*
- **PA-19** — Bases views

### Phase 4 — Habits & proactivity
- **PA-95** — hookable / own habit tracker → habit data into the review + briefing
- Proactive features: advance reminders, auto-create events for known future occurrences *(uses PA-100 + PA-102)*
- **PA-103** — assistant self-improvement loop (proposes Claude Code sessions)

### Phase 5 — Breadth & polish
- **PA-94** — per-project dev briefings
- **PA-15** — research skill *(also powers the agentic daily "teach me something")*
- **PA-25** applier diff-mode · **PA-26** multi-op refactor proposals
- **PA-22** test layer · **PA-23** model benchmark
- **PA-16** Goodreads sync · **PA-17** devops PR submission (v2) · **PA-24** Gmail/inbox *(deprioritized)*

## The critical path

The spine is **Phase 1**: `memory substrate (PA-102)` → `nudge (PA-100)` + `capture (PA-101)` → `briefing v2 (PA-96)` + `weekly review (PA-99)`. Build the OS first — it's what makes the 65 life-tasks (and every future one) actually get *done* instead of rotting. Everything after Phase 1 is enrichment on a loop that already works.
