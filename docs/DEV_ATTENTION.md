# Dev attention bridge — the assistant as Taylor's right hand across dev orchestrators

How the assistant reduces Taylor's role as the serialization point of his own
development pipeline. Spans two repos: this one (the assistant, which reads and
digests) and `emergent-npcs/npc-simulation` (whose orchestrators emit the
signals). First slice of the per-project dev briefing (PA-94); long-term it
feeds the self-improvement loop (PA-103) and the v2 dev-work tier
([DEVOPS.md](DEVOPS.md)).

## The problem

The npc-simulation project runs several Claude Code orchestrator sessions in
parallel (its `/work` skill dispatches thread agents into worktrees; sessions
carry PRs through automated review rounds to a human merge gate). Every one of
them ultimately blocks on the same person, in a small number of recurring
decision classes:

1. **Plan approval** — a `/work` session presents a plan and waits.
2. **Merge gate** — a PR's review round completes with zero findings; nothing
   merges until Taylor notices and acts. Deliberately human — the automation
   direction there *removed* auto-close/auto-merge paths after they misfired.
3. **Escalations** — sandbox denials, environment breakage, scope questions.
4. **Review-round routing** — conflicts and changes-requested rounds that need
   to be routed back to the owning session.
5. **Awareness** — simply knowing which of N concurrent sessions needs input
   *now*, across devices.

The cost is not the decisions — most take seconds. It is the **discovery tax**:
high-volume, low-decision-density text (review rounds, agent reports, PR
bodies) spread across channels (multiple Claude Code sessions, GitHub, two
Linear workspaces, chat), each of which must be polled to learn that nothing
needed him. That is fatigue with no throughput.

## Design goal

One attention-ordered decision queue, delivered on the channel Taylor already
reads everywhere (Telegram), where:

- every item is a **decision**, phrased as one line with a jump-back-in link;
- "nothing needs you" is an explicit, trustworthy answer — silence must be
  distinguishable from ignorance;
- the assistant filters and prioritizes; the human decides; **merging and
  approving remain human acts** on their native surfaces (GitHub, the
  orchestrator session).

This is the assistant's core inversion applied to dev work: the assistant does
the toil (scan, filter, rank), Taylor makes small high-agency calls.

## Phases

### Phase A — read-only PR digest (this document's landing PR)

What GitHub already knows, condensed. New pieces, all in `pa_mcp/`:

- **`dev_prs` tool** ([dev_attention.py](../pa_mcp/dev_attention.py)) — scans
  open PRs across the repos in `PA_DEV_REPOS` via the GitHub CLI (read-only)
  and groups them by attention bucket: conflict, CI-failing,
  changes-requested, looks-merge-ready, awaiting-review, draft.
- **`dev-briefing` skill** ([skills/dev-briefing/SKILL.md](../pa_mcp/skills/dev-briefing/SKILL.md))
  — composes the queue for Telegram, ordered by decision value, and archives it
  under `00 - Assistant/Briefings/Dev/`.

One deliberate epistemic rule, learned in npc-simulation orchestration:
**approved + CI-green + no-conflict is *not* merge-readiness.** Automated
review rounds run asynchronously; a cached "MERGEABLE" or an early approval can
precede a round that posts findings. The scan therefore reports
"looks-merge-ready" with an explicit verify-the-round caveat, never a verdict.

Trust: no new credentials, no write paths. `gh` runs with the host's existing
auth and only ever executes `gh pr list` queries. Degrades to a clear message
when unconfigured (the `calendar_read` pattern).

### Phase B — attention handshake (next)

Phase A sees only what GitHub shows. Decision classes 1 and 3 (plan approvals,
escalations) live inside orchestrator sessions and today reach Taylor only if
he is watching that session. The handshake: **orchestrators emit structured
attention items to a surface the assistant reads.**

Chosen surface: **the npc-simulation Linear workspace** (label + comment
convention on the issue nearest the decision, e.g. `needs:taylor`). Rationale:
orchestrators already hold Linear write credentials and conventions; items get
lifecycle (created → resolved) for free; no new infrastructure. The two Linear
workspaces are separate (verified: the npc-simulation API key sees only the NPC
team), so the assistant side needs a second read credential
(`LINEAR_API_KEY_NPC`) and a small multi-workspace extension to the Linear
tooling. The emission convention itself belongs to npc-simulation's rules and
is tracked on the NPC board.

### Phase C — reply routing (deferred, design needed)

Closing the loop: Taylor answers from Telegram ("approve lane B's plan",
"defer that finding") and the assistant routes the answer back to the owning
session. This crosses a real trust boundary — it turns the assistant into a
command channel into dev machines — so it gets its own design pass before any
implementation. Non-negotiables already known: merges happen on GitHub by the
human; approvals must be attributable and auditable; the relay must be a typed,
allowlisted vocabulary, not free-text command execution.

## Configuration

```
# .env / Hermes server env
PA_DEV_REPOS=emergent-npcs/npc-simulation,taylor1355/npc,taylor1355/personal-assistant
```

Use canonical `owner/repo` names (npc-simulation lives under the
`emergent-npcs` org; `gh` follows redirects from the old name, but config
should not rely on that).

## Backlog seeds (PA workspace)

To be created as PA issues (the authoring session had no PA-workspace Linear
access — the gateway machine does):

- Schedule the dev briefing as its own wake (separate cadence from the 7am
  personal briefing; end-of-workday is the natural slot). Part of PA-94.
- Multi-workspace Linear read (`LINEAR_API_KEY_NPC`) for Phase B.
- Phase C design doc: typed reply-routing vocabulary + audit trail.
