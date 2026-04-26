# personal-assistant

A multi-agent personal assistant. Obsidian + SMS as primary interfaces, Linear as issue-tracking backbone, every user-state mutation is a reviewable proposal. Python (NeMo Agent Toolkit) + Go (host-side services) + TypeScript (Linear CLI).

## Commands

```bash
# Python agent
uv sync --project agent                                      # install deps (PEP 735, dev included)
uv run --project agent pytest agent/tests -v                # run all tests
uv run --project agent ruff check agent                     # lint
uv run --project agent mypy agent/src                       # type-check
uv run --project agent personal-assistant-agent wake --reason=manual-test

# Linear (TS CLI; see docs/LINEAR_CONVENTIONS.md)
bash tools/linear whoami                                    # smoke test
bash tools/linear status                                    # board overview
bash tools/linear setup-labels                              # idempotent label population

# Go services (when implemented)
cd executor && go test ./... -count=1
cd executor && go vet ./...
```

`make help` lists conveniences. Tests must pass before any commit.

## Project Structure

```
agent/                  Python — root + subagents + tools (NeMo Agent Toolkit)
  src/personal_assistant_agent/
    cli.py                  typer entrypoint (wake, propose, version)
    models.py               Pydantic models (Proposal, frontmatter, etc.)
    agents/                 root + subagent prompts and dispatch
    tools/                  vault_read, proposal_enqueue, linear_cli
  tests/                    pytest, mocks subprocess + LLM
executor/               Go — applies approved proposals, host-side
sync/                   Go — two-way vault sync, host-side
dispatcher/             Go — debounced trigger batcher, host-side (TBD)
sms/                    Go — Twilio webhook, host-side (TBD)
devops/                 Go — v2 PR submission service, host-side (TBD)
tools/
  linear                bash wrapper around the TS CLI
  linear-pm/            TS CLI using @linear/sdk
config/                 *.yaml.example — committed; *.yaml — gitignored
docs/                   ARCHITECTURE, PROPOSAL_FORMAT, BUDGET, LINEAR_CONVENTIONS,
                        VAULT_ORGANIZATION, DEVOPS
.claude/
  rules/                project-specific principles (architecture, dev-patterns, testing)
  skills/               dev-time workflows (audit, pr, subagent-scaffold, trigger-wire)
  agents/               utility agents (code-quality, doc-alignment, expert-debugger,
                        pattern-auditor)
```

## Architectural Principles (full text in [.claude/rules/architecture.md](.claude/rules/architecture.md))

1. **Proposal queue invariant** — the agent container never mutates user state. Writes go through structured proposals, the executor applies them. Some Linear ops are auto-applied (still logged).
2. **Agentic dispatch** — root agent routes per-trigger to specialist subagents. No fixed pipeline.
3. **Event-driven, debounced** — host-side dispatcher batches events; agent wakes with batch in context, runs to completion, exits.
4. **Value-prioritized wakes** — every wake ranks tier-1 obligations / tier-2 user-interest / tier-3 backburner work, picks the most valuable thing it can do within budget.
5. **Token-budgeted** — daily/weekly hard caps; soft target; tier-3 self-throttles.
6. **Linear and Obsidian have distinct purposes** — no mirror. Linear is the issue tracker; Obsidian is knowledge + working notes.
7. **Configurable provider routing** — model selection is config; code paths are provider-agnostic except for native-feature branches.
8. **Decoupled vault** — the agent works on its own copy; sync daemon bridges to user's vault.
9. **Reusable with opinionated defaults** — onboarding a different user is config, not code.

Full design: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Anti-patterns

| Don't | Do |
|---|---|
| Agent code writing to the vault, calendar, email, or any user state directly | `proposal_enqueue` → executor applies after approval |
| Executor applying a proposal without schema validation | Validate against typed schema; reject unknown action types |
| Hardcoded vault paths, OAuth tokens, phone numbers, API keys in source | `config/user.yaml`, `config/providers.yaml`, or `.env` |
| Write credentials in the agent container | Host-side services hold creds; container is read-only |
| `while True` poll loops in the agent | Event-driven wakes; agent runs once and exits |
| Silent `if not x: return` at system boundaries | Log + early return — bugs should be visible at boundaries |
| Mutable default args (`def f(xs=[])`) | `def f(xs=None): xs = xs or []` |
| Mocking the proposal-queue invariant in tests (e.g., direct vault write) | Fix the code; tests prove the invariant |
| Going around `LinearClient` with raw subprocess calls | Use `LinearClient`; add a method if missing |
| Bare `except:` / `except Exception:` swallowing | Catch specific exception types; let unexpected ones propagate |
| Magic strings for action types / states / labels | Enums (Python) / typed constants (Go) / string-literal unions (TS) |
| Cross-language contracts as undocumented dicts | Pydantic on Python side, mirrored Go struct, mirrored TS type — same shape |
| Branch from main and merge later for in-flight work | Linear-issue-prefixed branches: `feature/PA-12-intake-agent`; PR per issue |

## Code Style

- **Python**: type hints throughout. `from __future__ import annotations`. `snake_case` / `PascalCase` / `SCREAMING_SNAKE_CASE`. `_prefix` for private. Pydantic models for data crossing process boundaries. Comments explain *why*; identifier names cover *what*. Write timelessly — no "new", "old", "future" in comments.
- **Go**: `gofmt` + `go vet`. Idiomatic camelCase / PascalCase. Wrap errors with `fmt.Errorf("...: %w", err)`. No `panic` in service code; return errors. Package-level docs on every public package.
- **TypeScript**: strict mode (already on). Avoid `any` without inline justification. Explicit return types on exported functions. Prefer string-literal unions over enums for serialization-facing types.
- **Universal**: early returns, flat over nested. One responsibility per function. If a function description needs the word "and" twice, split it.

Full guidelines: [.claude/rules/development-patterns.md](.claude/rules/development-patterns.md).

## Skills (dev-time, in `.claude/skills/`)

| Skill | Purpose |
|---|---|
| `/audit [path]` | Adversarial review: bugs, gaps, stale docs, missing tests |
| `/pr [pr-number]` | PR pipeline: lint → test → docs → commit → create PR |
| `/subagent-scaffold` | Generate a new subagent file with consistent shape |
| `/trigger-wire` | Wire a new wake trigger end-to-end (source + handler + config + tests) |

Utility agents (used by skills): `code-quality`, `doc-alignment`, `expert-debugger`, `pattern-auditor`.

Runtime capabilities of the assistant itself (not skills) live in `agent/` and `docs/PROPOSAL_FORMAT.md`.

## Process

- **Never commit without user approval.** Never push without being asked.
- **Read code before editing.** Verify signatures, check existing patterns, test assumptions.
- **Run tests before proposing commits.** Full suite must pass; flaky tests get fixed or filed as Linear issues, not skipped.
- **Focused commits** — separate fixes, refactors, docs. Reference Linear issues in commit subjects when working from one (`feat(agent): debounced inbox dispatcher (PA-12)`).
- **Pre-existing failures**: don't paper over. File a Linear issue with the `bug` label and proceed; don't let it block unrelated work.
- **Linear lifecycle is automatic** — `pickup` on start, `done` on PR merge / proposal applied, stale-revert by daily job. Don't manually transition issues you're working on.
- **Branch naming**: `<type>/PA-<id>-<slug>` where type ∈ {feature, fix, refactor, docs, chore}.

## Commit Messages

```
type(scope): short subject (PA-NN)

Body explains *why* in 1-3 short paragraphs. List affected files only
if non-obvious. Note breaking changes or migration steps.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```

Types: `feat`, `fix`, `refactor`, `docs`, `chore`, `test`, `perf`. Scopes follow the project structure: `agent`, `executor`, `sync`, `tools`, `docs`, `infra`.

## Reference Index

| Topic | Location |
|---|---|
| Architecture, components, capability tiers | [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) |
| Proposal file schema + validation | [docs/PROPOSAL_FORMAT.md](docs/PROPOSAL_FORMAT.md) |
| Token spend caps and self-throttling | [docs/BUDGET.md](docs/BUDGET.md) |
| Linear labels, priorities, states, templates | [docs/LINEAR_CONVENTIONS.md](docs/LINEAR_CONVENTIONS.md) |
| Frontmatter schemas + Bases view library | [docs/VAULT_ORGANIZATION.md](docs/VAULT_ORGANIZATION.md) |
| v2 dev-work spec | [docs/DEVOPS.md](docs/DEVOPS.md) |
| Project-specific architectural rules | [.claude/rules/architecture.md](.claude/rules/architecture.md) |
| Code style + common patterns | [.claude/rules/development-patterns.md](.claude/rules/development-patterns.md) |
| Testing patterns | [.claude/rules/testing.md](.claude/rules/testing.md) |
| Linear backlog (PA team) | linear.app — team Personal Assistant, prefix `PA-` |
