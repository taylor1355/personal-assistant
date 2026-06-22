---
name: plan-work
description: Turn Taylor's Linear board + vault todos into a prioritized, sequenced plan, drafted for review. Use when asked to "plan my week/day", "what should I work on", "help me plan", or to triage vague todos into Linear.
---

# Plan work

Turn what's tracked (Linear) and what's loose (vault todos) into one clear,
sequenced plan. Treat the week as a battlefield: dispatch blockers and quick
high-value wins first, then protect time for the single deep-work objective,
then defer the rest. **Draft only — do NOT create or change any Linear issue
unless Taylor explicitly confirms.**

## Gather FIRST — do not skip

**You MUST call `today`, `linear_board`, and `linear_todo`, plus `vault_list`
on `02 - Todos`, BEFORE writing anything.** Then `vault_read` the 1–2 most
relevant todo files for specifics. Use only what the tools return — never
invent issues, todos, or dates.

## Analyze

- **What's the single most valuable objective** for the near term, and why?
- **What order?** Lead with unblockers and fast high-value wins, then the main
  objective, then defer low-leverage work. Call out anything blocked or
  time-sensitive, and any dependencies between items.
- **What's loose?** Which vague vault todos are NOT yet tracked in Linear and
  should be?

## Draft → `00 - Assistant/Plans/<YYYY-MM-DD> Plan.md` (via `assistant_write`, date from `today`)

- **Objective** — the one thing that matters most this week.
- **Sequenced plan** — an ordered list (1, 2, 3…), each item one line with a
  short rationale (why now / why this order). Reference Linear IDs where they exist.
- **Proposed new issues** — loose todos that should become Linear issues: for each,
  a title + suggested type (`type:feature` / `bug` / `tech-debt` / `investigation` /
  `docs`) and priority (1=Urgent … 4=Low). Mark these PROPOSED — do not create them.
- **Proposed board changes** — priority bumps or `blocks` links worth setting
  (proposed, not applied).

## Reply

A 3–4 line summary + the plan's file path, then ask: **"Want me to create the
proposed issues and apply the board changes?"** Only on an explicit *yes* do you
call `linear_create` / `linear_set_priority` / `linear_link` — and report each
change you make.
