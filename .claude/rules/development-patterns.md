# Development Patterns

Idioms and conventions specific to this codebase. The architectural invariants live in [architecture.md](architecture.md); this file is about *how* to write code that fits.

## Configuration

Three layers, in increasing specificity:

1. **`config/*.yaml.example`** — committed, read-only reference. Documents every knob and its default.
2. **`config/*.yaml`** — gitignored, the actual values used. Same shape as the example.
3. **`.env`** — gitignored, secrets only. API keys, OAuth tokens. Read by services that need them.

Loading discipline:
- Python: a single `Config` object built at wake start, passed down. No re-reading config in inner functions; if a function needs a value, take it as a parameter.
- Go: env at process start; flag-overrides via `flag.String(..., os.Getenv("FOO"), ...)` for CLI-friendly defaults.
- TS: `process.env.FOO` directly is fine for the small Linear CLI; not for anything larger.

If a config key is added, update three places in the same commit: the `*.example` file, the loader, and the documentation that references the key. The `doc-alignment` agent will catch missed updates.

## Logging

We don't have a project-wide structured logger yet. Until we do:

- **Python agent**: write a single line per significant event to stdout (which the wake captures into the session log file). Format: `agent: <subagent or component>: <verb past tense> <subject>` (e.g., `agent: journal_agent: emitted 1 proposal`). Errors go to stderr.
- **Go services**: `log.Printf` with structured key=value pairs. One day this gets replaced with `slog`; until then, prefer key=value over freeform prose so we can grep.
- **TS CLI**: stdout for human-readable, exit code for success/fail. Don't use stderr for normal output.

Anti-pattern: scattering `print` calls everywhere for "diagnostics." If something's worth logging, it's worth a deliberate one-liner; otherwise it's noise.

## Errors

- **Python**: subclass concrete exceptions for domain errors (`ProposalCollision`, `LinearError`, `VaultPathError`). Bare `except:` and broad `except Exception:` are forbidden outside the very top of a wake (where the root catches everything to write a session log). Catch the specific types you intend to handle.
- **Go**: return `error` everywhere; wrap with `fmt.Errorf("context: %w", err)` when crossing module boundaries. Don't `panic` outside `main()`/test setup; `panic` is for "this can't happen and the program is broken."
- **TS**: throw `Error` subclasses; let the top-level `main().catch(...)` log and exit non-zero. Don't catch and silence.

The system-boundary rule from npc-simulation applies: `if not x: return` without logging at a process boundary hides real bugs. Either the input invariant should be enforced upstream (then this is dead code), or this is a real failure mode (then it deserves a log line).

## Subprocess

Patterns for shelling out (relevant for `LinearClient` and the future `devops` service):

- Use `subprocess.run(..., check=False)` and check the returncode yourself; raise a domain exception with stdout + stderr + cmd attached. Don't use `check=True` — the bare `CalledProcessError` doesn't carry stderr cleanly.
- Pass env explicitly via `env=` to inject API keys, not by mutating `os.environ`.
- Cross-platform: invoke `npx`, `node`, `git`, `gh` directly without shell wrappers. Bash scripts work in dev but break in containers and on Windows.
- Encoding: always `text=True, encoding="utf-8"`. Don't trust system locale.

## Cross-Language Boundary Discipline

When a contract crosses Python ↔ Go ↔ TS:

- The schema lives in one place (Pydantic for proposal frontmatter, TS types for Linear CLI I/O, Go structs for executor-internal types). The other side mirrors it manually with a comment pointing at the source.
- Every PR that changes a boundary contract MUST update both sides + the spec doc that describes it. The audit skill checks for this; the doc-alignment agent flags drift.
- For string-valued enums (action types, Linear states, label names): use `Enum` in Python, `string` constants grouped in a struct in Go, and string-literal unions in TS. Avoid actual TypeScript `enum` (different runtime semantics).
- Time: ISO 8601 UTC strings everywhere on the wire. Local-time conversion happens at display layer only.

## Pydantic + Typing Conventions

- All data crossing process boundaries: Pydantic `BaseModel` with `extra="forbid"` and `frozen=True`. Closed schemas catch typos; frozen models prevent accidental mutation.
- All async LLM calls / I/O: type the response shape with Pydantic, validate immediately. The cost of a missing field surfacing here vs deep in business logic is huge.
- `from __future__ import annotations` at the top of every module. Lets you use forward references and generic syntax cleanly.
- Type hints on every function signature. `mypy` is the canonical checker; it runs in `code-quality` agent's `verify` mode.
- Avoid `Any` outside of intentional escape hatches. When you do need it, comment why.

## Testing

Full conventions: [testing.md](testing.md). The most important pattern from npc-simulation that transfers verbatim:

> Every test must have **regression value** — it should fail if the behavior it documents changes. Before writing a test, ask: "What future code change would make this fail?" If the answer is "nothing realistic," the test is tautological.

Mock the boundaries (subprocess, LLM API calls), not the project's own logic. If a test needs to mock something inside the package, that's a design signal — flag and refactor.

## File Organization

Keep modules small. If a file approaches 300 lines, look for a natural split:
- `agents/journal_agent.py` is fine at 200 lines because it's one cohesive responsibility.
- `tools/proposal_enqueue.py` and `tools/vault_read.py` are separate because they're independent.

Don't preemptively split for "future flexibility." Three similar lines is better than a premature abstraction. Let the abstraction emerge when you have three concrete cases that share shape.

## Subagents Have a Standard Shape

Defined in [.claude/skills/subagent-scaffold/SKILL.md](../skills/subagent-scaffold/SKILL.md). Every subagent file declares:

1. **Reads from**: which tools it calls
2. **Writes through**: always `proposal_enqueue` (or `LinearClient` for auto-applied Linear ops)
3. **Emits proposal action types**: which `action` values it can produce
4. **Triggers it serves**: which wake reasons route to it
5. **Escalation conditions**: when it sends SMS or writes a session-log warning

These show up as a docstring at the top of the file and as the subagent's prompt context. Drift between them and reality is what `doc-alignment` catches.

## Module Lifecycle

Per-process boundaries:

- **Python agent**: one process per wake. Module-level state is fine because the process exits; don't write code that assumes a long-lived module-level cache.
- **Go services**: long-running. Module-level state must be safe-to-share or guarded; package-init fns shouldn't do I/O beyond what's in `main()`.
- **TS CLI**: one process per command. Same as Python — module init is cheap.

## Idempotency

Where the agent's actions might fire twice (debounced trigger double-firing, webhook retry, dispatcher restart):

- Proposal filenames carry `YYYY-MM-DD-HHMM-<slug>`; same wake → same minute → same slug → collision detected at write time (`ProposalCollision`).
- Linear writes are idempotent at the API level for `update`; for `create`, the agent should check before creating (or accept rare duplicates and clean them in pm_agent's triage).
- Vault writes via the executor are atomic (tempfile + `os.replace`); a failed apply leaves the proposal in `failed` state for retry.

If you're tempted to add a "have I done this already?" cache, prefer encoding idempotency in the protocol (filename, ID generation) over carrying state.

## Don't Reinvent

Before writing a new helper:

- Search `agent/src/personal_assistant_agent/` and `tools/linear-pm/src/` for an existing one. The `pattern-auditor` agent is built for exactly this.
- Existing helpers worth knowing: `read_vault_file`, `enqueue` (proposals), `LinearClient`, `_yaml_quote`, `_unified_diff`, `extract_journal_section`. They cover most filesystem/text/Linear needs.
- If the existing helper is *almost* right, extend it rather than copy-paste.
