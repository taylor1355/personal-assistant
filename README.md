# personal-assistant

A multi-agent personal assistant that uses Obsidian as its primary interface and treats every write as a reviewable proposal.

**Status: pre-alpha, design phase.** The repo layout, config shape, and runtime behavior are all unstable. Not yet runnable end-to-end.

## What it is

- **Agentic, not scripted.** A root agent dispatches to specialized subagents (email, calendar, journal, vault organization, research, reading) and tools. No fixed pipeline — which subagents run depends on the trigger.
- **Obsidian-native.** The user's vault is the primary interface surface: assistant writes go into `00 - Assistant/` (proposals, daily digests, session logs); user messages go into an inbox note the assistant watches.
- **SMS as secondary channel.** Two-way texting for urgent or away-from-desk interaction.
- **Read-only external access + proposal queue for writes.** The agent container has read-only access to Gmail, Calendar, etc. Every mutation — to the vault, calendar, email, anywhere — flows through a proposal queue reviewed and approved by the user. A separate privileged executor (outside the container) applies approved proposals.
- **Event-driven.** The agent sleeps and wakes on specific triggers: new inbox content, batched email ticks, inbound SMS, scheduled jobs. No continuous polling.
- **Configurable provider routing.** Mix local models (Ollama) with cloud APIs (OpenRouter, Anthropic native, etc.) per task. Flip to all-local or all-cloud via config.

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the full design.

## Scope

The MVP targets three tasks that together exercise every axis of the architecture:

1. **Todo-completion detection** — agent reads today's journal, detects mentions of completed todos, proposes edits to the short-term todos file.
2. **Dated-plan reminders** — agent monitors `04 - Plans/Dated/YYYY-MM-DD <slug>.md` files, proposes reminders as they approach, archives them after they pass.
3. **Goodreads ↔ vault sync** — agent keeps the reading list in the vault synced with Goodreads.

Beyond the MVP: vault organization improvement (frontmatter, tags, MOCs), calendar-aware scheduling, email triage, web research.

## Design philosophy

Opinionated defaults, clean configuration. Built primarily for the author, but structured so that forking and pointing it at a different vault / phone / Google account is a config change, not a code change. The longer-term goal is that a less technical user (say, a parent) could have this stood up for them and use it through Obsidian and SMS without touching the internals.

## License

MIT — see [LICENSE](LICENSE).
