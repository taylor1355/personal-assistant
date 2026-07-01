---
name: daily-briefing
description: Compose Taylor's morning briefing from Linear + the Obsidian vault and save it to the assistant area. Use when asked to "brief me", for a daily digest, or on the morning wake.
---

# Daily briefing

Produce one concise, scannable briefing for today and SAVE it to the vault. The
goal is to lay out the day, keep Taylor informed, and steadily improve via his
feedback. Treat his calendar as a battlefield and his tasks as objectives to
dispatch efficiently — but only with facts you actually pulled from tools.

## Gather FIRST — do not skip

This is Taylor's **personal** briefing — his life-tasks + calendar. Assistant/dev
issues (the PA-dev backlog) are **out of scope** here; they get a separate dev
briefing. **You MUST call `today`, `calendar_read`, and `linear_personal` BEFORE
writing anything.** Compose only from what the tools return; a section is
"nothing today" ONLY when its tool genuinely returned nothing. Never invent
tasks, dates, or events.

Steps:

1. `today` → the date; use it for the filename and any "today/this week" reasoning.
2. `calendar_read` → today's events (read-only). "No events." = a clear day; a
   "not configured/failed" message → say the calendar is unavailable in one line.
   Never invent events.
3. `linear_personal` → Taylor's life-tasks (the Personal project, grouped by
   state). This is the backbone of the briefing; lead with what's due/overdue and
   time-sensitive.
4. Optional: `vault_read` a note or two for context on a specific task. Do NOT
   mine the `02 - Todos` lists — life-tasks live in Linear now.

## Compose

Write a short, scannable personal briefing:

- **Top priority** — the single most valuable life-task today (due/time-sensitive first), and why.
- **Schedule** — today's timed events from `calendar_read`, earliest first (e.g. "17:45 Power Yoga"); note all-day items briefly. Shape the day around these fixed commitments. Omit only if the day is genuinely clear.
- **Today's focus** — up to 3 concrete life-tasks, fitted around the schedule.
- **On deck** — a few notable upcoming life-tasks from `linear_personal` (by title; IDs optional).
- **Watch-outs** — anything time-sensitive, overdue, blocked, or waiting-for (a due date approaching, a "waiting-for" item to chase).
- **One thing to learn** — a brief, genuinely useful pointer tied to Taylor's actual work/interests (skip if nothing fits — don't pad).
- **Feedback** — one specific question that would make tomorrow's briefing better.

Calendar is wired (`calendar_read`); email is not (deprioritized). Dev work is tracked separately — don't fold PA-dev issues into this personal briefing. Never fabricate events or tasks.

## Save and deliver

- First `assistant_write` the briefing to `00 - Assistant/Briefings/<YYYY-MM-DD>.md` (date from `today`) — the durable archive.
- Then make your FINAL reply the **full briefing itself** — it is delivered straight to Taylor on Telegram, so send the whole thing, not a summary or a file path.
- Format for a phone: short, with `*bold*` section labels and `-` bullets. Do NOT use Markdown tables or `#` headers — they don't render cleanly on Telegram. Keep it scannable in one message.
