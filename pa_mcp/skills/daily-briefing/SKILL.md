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

**You MUST call `today`, `linear_board`, and `linear_next`, plus at least one
`vault_list`, BEFORE writing anything.** Compose only from what they actually
return. A section is "nothing today" ONLY when its tool genuinely returned
nothing — if `linear_board` shows in-progress or backlog issues, they MUST
appear (do not write "none" when the tools returned data). Never invent issues,
todos, dates, or events.

Steps:

1. `today` → the date; use it for the filename and any "today/this week" reasoning.
2. `linear_board` and `linear_next` → what's in progress, what's on deck, and the
   single highest-priority unblocked issue.
3. `vault_list "02 - Todos"` and `vault_list "04 - Plans"` → active todos and
   upcoming/dated plans. `vault_read` the 1–2 files most relevant to today for
   specifics. (Folder+filename carry the meaning — there are no tags/frontmatter.)
4. Optional, if cheap: skim `06 - Learning` for a relevant micro-lesson.

## Compose

Write a short, bolded-where-it-counts briefing with these sections:

- **Top priority** — the single most valuable thing to do today, and why.
- **Today's focus** — up to 3 concrete things (bullets, each ~1 line).
- **In flight** — the **In Progress** issues from `linear_board`, each by ID + title (this is rarely empty — check `linear_board` output before writing "none").
- **On deck** — the top 2–3 **Backlog** issues from `linear_board` (by ID + title), plus the most relevant active vault todos.
- **Watch-outs** — anything time-sensitive, blocked, or at risk.
- **One thing to learn** — a brief, genuinely useful pointer tied to today's work (skip if nothing fits; don't pad).
- **Feedback** — ask ONE specific question that would make tomorrow's briefing better (e.g. "Was 'On deck' useful, or noise?"). Invite Taylor to reply in chat or jot a note.

Calendar and email aren't wired yet (coming in v1) — say so in one line if relevant; do not fabricate events or messages.

## Save and deliver

- First `assistant_write` the briefing to `00 - Assistant/Briefings/<YYYY-MM-DD>.md` (date from `today`) — the durable archive.
- Then make your FINAL reply the **full briefing itself** — it is delivered straight to Taylor on Telegram, so send the whole thing, not a summary or a file path.
- Format for a phone: short, with `*bold*` section labels and `-` bullets. Do NOT use Markdown tables or `#` headers — they don't render cleanly on Telegram. Keep it scannable in one message.
