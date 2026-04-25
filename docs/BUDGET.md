# Budget

Spec for token-spend caps and self-throttling. The agent enforces these before any LLM call. Source of truth for tier classification is the wake's chosen action; source of truth for spend is the provider's per-request usage report.

## Caps

Three caps per scope. Two block, one shapes behavior.

| Cap | Default | Behavior |
|---|---|---|
| Daily hard | $10 | Blocks: no LLM call may execute if it would exceed remaining daily budget. |
| Weekly hard | $30 | Blocks: same as daily, but for rolling 7-day window. |
| Daily soft | $3 | Self-throttles: tier-2 and tier-3 work declines to start when remaining daily budget is below `daily_hard - daily_soft` (i.e., when soft cap is exhausted). Tier-1 work proceeds. |
| Backburner share (tier-3) | $1/day baseline | Self-throttles: tier-3 work declines to start when its rolling-7-day spend exceeds 7× this value. |

Defaults live in `config/user.yaml` under `budget:` and can be tuned without code changes.

```yaml
budget:
  daily_hard_usd: 10
  weekly_hard_usd: 30
  daily_soft_usd: 3
  tier3_daily_usd: 1
```

## Tier classification

Every wake the root agent classifies its planned action into one tier. Mid-wake escalation is allowed (an investigation reveals an urgent obligation) but de-escalation is not (you don't quietly downgrade an obligation to backburner).

- **Tier 1 — time-sensitive obligation.** SMS replies owed, imminent calendar items (next 2 hr), todo-completion detection on a journal that just landed, Linear issues with deadlines in the next 24 hr.
- **Tier 2 — advanceable user interest.** Top of Linear `Todo` ranked by priority + recency, in-progress issues that can take a step, vault-organization for a folder where it's the next blocker.
- **Tier 3 — long-horizon backburner.** Research issues, exploratory work, R&D programs, vault-organization that's nice-to-have rather than blocking.

## Enforcement

Every LLM call goes through a `Budgeter` instance the agent constructs at wake start. Sequence per call:

1. Estimate cost. The Budgeter knows the route (provider + model) and uses the provider's published prices plus a token estimate (prompt tokens × input_price + max_tokens × output_price as a worst-case ceiling).
2. Check caps in this order — daily hard, weekly hard, daily soft (only for tier ≥ 2), tier-3-share (only for tier 3).
3. If any block-cap would be breached: raise `BudgetExceeded`. The wake catches at the root, writes a session-log entry explaining what was skipped and why, and exits cleanly. No partial work.
4. If a self-throttle cap would be breached: the agent picks a different action (drop to tier 1 obligations only, or end the wake if there are none).
5. After the call returns, record actual usage from the provider response. Estimates are corrected; subsequent calls in the same wake see the updated remaining budget.

## Spend ledger

`var/agent/spend.jsonl` — append-only log on the host (mounted into the container read-write but only this path). One JSON line per LLM call:

```json
{"at":"2026-04-25T14:23:00Z","wake_id":"abc12","tier":2,"subagent":"research_agent","provider":"anthropic","model":"claude-opus-4-7","input_tokens":12453,"output_tokens":1832,"cost_usd":0.243}
```

The Budgeter reads the ledger at wake start to compute remaining caps. Daily/weekly windows are computed in `USER_TIMEZONE` so cap rollover happens at user-local midnight, not UTC.

## What's NOT in the budget

- Local Ollama calls — zero LLM cost; only physical resource cost which is the user's GPU. Logged for diagnostics, not budgeted.
- Linear/Gmail/Calendar API calls — bounded by external rate limits, not by token spend. Not budgeted here.
- Anthropic / OpenRouter free-tier credits — the budgeter charges as if they were paid. Conservatism prevents surprises when the credits exhaust.

## Observability

A `budget` summary appears in every session log:

```markdown
## Budget
- Tier: 2 (advanceable interest)
- This wake: $0.34 / 5 LLM calls
- Today: $1.82 / $10.00 hard, $3.00 soft (active)
- Week: $7.41 / $30.00 hard
- Tier-3 7d: $0.61 / $7.00
```

The numbers feed the daily morning digest, so the user sees a running view of spend without opening a separate dashboard.

## Self-improvement signal

If the agent hits its soft cap repeatedly without the user marking the work as valuable, that's a signal to (a) tighten model routing (prefer cheaper providers for similar tasks) or (b) reduce ambition on tier-2/3. The agent can propose budget adjustments via the proposal queue, but defaults stand until the user approves.
