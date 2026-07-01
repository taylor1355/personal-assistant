# Session Handoff — 2026-07-01

How to pick up after the design-examination + mega-intake session. Pair with
[ROADMAP.md](ROADMAP.md) and the auto-memory files (`project-productivity-system`,
`project-assistant-capabilities`, `project-todos-in-linear`, `user-relationships`).

## Live today

- **v0**: local Hermes + `qwen3.6`, Telegram bot, 7am briefing cron.
- **v1 write path** (PA-3): `propose` → approve (Obsidian status-flip) → applier; the applier runs as a Windows scheduled task **PA-ApplyProposals** every 10 min.
- **Calendar** (PA-14): read-only Google Calendar in the briefing.
- **Life-task system**: ~65 SMART issues in the Linear **Personal** project (mega-intake): 8 epics + singles, GTD context labels (`@online/@call/@home/@deep-work/@errand/@anywhere/waiting-for`), fibonacci estimates, due dates.

## Open PRs — YOU merge (I'm deny-listed from `gh pr merge` now)

| PR | What | Status |
|---|---|---|
| #7 | Personal-first briefing (PA-30) | clean; **deploy after merge** |
| #6 | Roadmap + this handoff | feedback addressed |
| #2 | pr-review / pr-address-review skills + quality bar | feedback addressed (this is the "pr-address-feedback" skill) |
| #8 | Claude PR automation + permissions deny list | **needs `ANTHROPIC_API_KEY` repo secret** |
| #1 | Wire wake CLI (PA-1) | ⚠️ touches **pre-pivot NeMo code** (`agents/`, `cli.py`) the live system doesn't use — **recommend closing as obsolete** rather than merging dead code |

## Deploy / ops after merging

- **PA-30 briefing**: update the deployment's `pa_mcp` checkout + restart the Hermes gateway; run "brief me" to confirm it's personal-only (life-tasks + calendar, no dev board).
- **Claude workflows (#8)**: add the `ANTHROPIC_API_KEY` secret (Settings → Secrets → Actions). Gemini's consumer review is sunsetting (July 2026), so Claude review is the successor.
- **Merges are a human step** by design (deny list). Destructive git/gh/rm commands are also deny-listed.

## Next work — Roadmap **Phase 1 (the "OS")**, highest leverage

The anti-rot operating system: `PA-102` memory/situational-awareness → `PA-100` nudge + `PA-101` capture → `PA-96` briefing v2 + `PA-99` weekly review. This is what turns the 65 tasks from a list into an assistant that keeps you on track. Backlog filed this session: **PA-93–103** (+ PA-25/26).

## Design decisions this session (all in memory)

- **Todos = Linear** (Personal project), SMART only; ideas/aspirational/habits stay in vault notes.
- **Anti-rot**: build the loops (review/capture/nudge); **decouple** them; **invert the ratio** (assistant does the toil, you make small high-agency calls) — grounded in your own 2024 weekly-focus/goal/retro process (which rotted from coupling + manual load).
- **Briefing v2**: personal-first, synthesized into loose blocks (morning/afternoon/evening), capacity-aware (Raleigh in-person Mon/Tue, remote Wed–Fri), inferred leverage, a *researched* personalized daily lesson.
- **Semantic knowledge layer**: vault entity notes — freeform bodies + earned structured fields + rich metadata/tags; hybrid NL/structured/graph/tree retrieval.
- **Self-improvement loop**: the assistant proposes Claude Code sessions to edit its own prompts/skills/memory.
- **"A good assistant nags"**: persistent, calibrated follow-up (weekly review kicks off Sat ~10am, escalating until done).
- **Habits** stay in Loop for now → hookable/own tracker (PA-95).

## Gotchas

- Linear: workspace **npc-simulation**, team **PA**; life-tasks in the **Personal** project; `bash tools/linear` (node-direct on Windows).
- The main checkout is on `feature/PA-7` with an uncommitted `linear_cli.py` change (pre-existing, not from this session).
- `PA-53` (Rahul's puzzle) still needs a due date (his birthday minus one).
