---
name: dev-briefing
description: Compose Taylor's cross-repo dev briefing — what needs a human decision across his development orchestrators (PRs, dev backlog) — and save it to the assistant area. Use when asked "what needs me?" about dev work, for a dev digest, or on a scheduled dev wake.
---

# Dev briefing

Produce one attention-ordered, scannable dev briefing and SAVE it to the vault.
This is the **dev** counterpart of the personal daily-briefing: Taylor runs
several Claude Code orchestrator sessions in parallel (npc-simulation and
friends) and the bottleneck is knowing *which item needs his decision right
now* without reading every channel. Your job is to filter volume down to
decisions. Personal life-tasks are OUT of scope here — they belong to the
daily briefing.

## Gather FIRST — do not skip

**You MUST call `today`, `dev_prs`, and `linear_board` BEFORE writing
anything.** Compose only from what the tools return. Never invent PRs, issues,
or review states.

1. `today` → the date; use it for the filename.
2. `dev_prs` → open PRs across the configured repos, already grouped by
   attention bucket. If it reports "not configured", say so in one line and
   continue with what you have.
3. `linear_board` → the PA dev backlog (this workspace only; the npc-simulation
   Linear board is a separate workspace the tools cannot see yet — never claim
   its issues are absent, say "not visible from here" if relevant).
4. Optional: `vault_read` a note for context on a specific item.

## Compose

Order by decision value, not by repo:

- **Needs you now** — items only Taylor can unblock, most urgent first: merge
  conflicts to route, failing CI to route, changes-requested rounds. One line
  each: repo, PR number, what the decision is. Include the URL — it is the
  jump-back-in link.
- **Ready to merge (verify first)** — PRs the scan calls looks-merge-ready.
  ALWAYS carry the caveat: approved + green is not merge-ready until the
  latest review round completed with zero findings; say "verify the last
  round, then merge from the GitHub app".
- **In flight, nothing owed** — a compact count ("4 PRs awaiting review
  rounds"), names only if few. This section exists so silence is
  distinguishable from ignorance.
- **Dev backlog highlights** — top Todo items from `linear_board`, only if
  they warrant attention today.
- **Feedback** — one specific question that would make the next dev briefing
  better.

An empty "Needs you now" is a valid, valuable answer — say "nothing is waiting
on you" plainly. Never pad.

## Save and deliver

- First `assistant_write` to `00 - Assistant/Briefings/Dev/<YYYY-MM-DD>.md`
  (date from `today`).
- Then make your FINAL reply the **full briefing itself** — it goes straight
  to Taylor on Telegram. Phone formatting: `*bold*` labels, `-` bullets, no
  Markdown tables, no `#` headers, scannable in one message.
