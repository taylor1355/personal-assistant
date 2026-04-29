# personal-assistant

A multi-agent personal assistant that uses Obsidian + SMS as its primary interfaces, Linear as its issue-tracking backbone, and treats every user-state mutation as a reviewable proposal.

**Status: pre-alpha, design phase + v0 landed.** v0 ships the proposal loop end-to-end on todo-completion detection. v1 is the "useful daily" version (in active design + early implementation). Repo layout, config, and runtime behavior are still mutable.

## What it is

- **Agentic, not scripted.** A root agent dispatches per-trigger to specialist subagents (intake, journal, calendar, email, vault organization, research, reading, PM, Linear, devops). No fixed pipeline — the wake's trigger and current value-priority pick the path.
- **Unified capture+command.** One inbox note + one SMS thread. You dump raw text, give instructions, ask questions; an `intake_agent` classifies and routes. No formatting required, no command syntax.
- **Event-driven, debounced.** A host-side dispatcher batches events with quiet/max-delay/buffer policies and wakes the agent with the batch in context. No long-running poll loops.
- **Value-prioritized wakes.** Every wake asks "what's the most valuable thing I can do right now?" Tier 1: time-sensitive obligations. Tier 2: advanceable user interests from the Linear backlog. Tier 3: long-horizon backburner. Token-budgeted; tier-3 work fills spare cycles when you're unavailable.
- **Read-only external creds + proposal queue for writes.** The agent container has read-only Gmail / Calendar / Linear-team access. User-state mutations (vault writes, calendar/email writes) go through a proposal queue you review in Obsidian. Mechanical Linear ops (status transitions, label updates) are auto-applied but still logged.
- **Linear is the issue tracker; Obsidian is knowledge + working notes.** Distinct surfaces, no mirror. Vault organization is its own first-class capability — the `vault_organizer` subagent incrementally proposes frontmatter and Obsidian Bases views over your existing notes.
- **Dev work, eventually.** v2 lets the agent pick up code-typed Linear issues and submit PRs to your repos (starting with this one). PR review is the approval gate; no special proposal needed.
- **Configurable provider routing.** Mix local models (Ollama) with cloud APIs (Anthropic, OpenRouter) per task class. Flip to all-local or all-cloud via config. Hard daily/weekly token budgets.

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the full design.

## Capability tiers

| Tier | Capability | Status |
|---|---|---|
| **v0** | Proposal loop end-to-end on todo-completion detection | shipped |
| **v1** | Useful daily — intake / dispatcher / value-priority / Linear / vault-organization / digest | in design + early implementation |
| **v2** | Agent-authored PRs to allowed repos | spec'd, deferred |
| **v3+** | Open — emerges from running v1+v2 | TBD |

## Getting started

See [docs/GETTING_STARTED.md](docs/GETTING_STARTED.md) for the full setup walk-through (toolchain installs, secrets, first run, troubleshooting). The short version: install `uv`, `node`, `gh`; clone; copy `.env.example → .env` and fill in `ANTHROPIC_API_KEY` + `LINEAR_API_KEY`; `uv sync --project agent`; `bash tools/linear whoami` to smoke test.

## Spec docs

- [docs/GETTING_STARTED.md](docs/GETTING_STARTED.md) — setup, first run, common operations
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — overall design, components, capability tiers
- [docs/PROPOSAL_FORMAT.md](docs/PROPOSAL_FORMAT.md) — proposal file schema
- [docs/BUDGET.md](docs/BUDGET.md) — token spend caps and self-throttling
- [docs/LINEAR_CONVENTIONS.md](docs/LINEAR_CONVENTIONS.md) — labels, priorities, states, issue templates
- [docs/VAULT_ORGANIZATION.md](docs/VAULT_ORGANIZATION.md) — frontmatter schemas + Bases view library
- [docs/DEVOPS.md](docs/DEVOPS.md) — v2 dev-work spec

## Design philosophy

Opinionated defaults, clean configuration. Built primarily for the author, but structured so that forking and pointing it at a different vault / phone / Google account / Linear team is a config change, not a code change. Longer-term goal: a less technical user (say, a parent) could have this stood up and use it through Obsidian + SMS without touching the internals.

## Running it (current state)

After completing setup per [docs/GETTING_STARTED.md](docs/GETTING_STARTED.md), v0 (journal-completion detection) runs end-to-end:

```bash
ANTHROPIC_API_KEY=sk-ant-... \
  VAULT_ROOT="/path/to/your/Obsidian/vault" \
  PROPOSALS_PATH="./var/proposals" \
  USER_TIMEZONE="America/New_York" \
  uv run --project agent personal-assistant-agent wake --reason=journal
```

Reads today's journal section + the short-term todos, asks Claude which todos look done, writes one proposal per detected completion. The executor (still a stub — PA-3 in the backlog) is what would apply approved proposals back to the vault.

The inbox flow (`wake --reason=inbox`) is wired but needs PA-1 to land before the CLI passes a `LinearClient` through to it.

## License

MIT — see [LICENSE](LICENSE).
