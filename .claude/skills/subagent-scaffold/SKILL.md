---
name: subagent-scaffold
description: Scaffold a new personal-assistant subagent (email_agent, reading_agent, etc.) with consistent shape — prompt, tool registration, proposal types, tests.
argument-hint: "[subagent name] [one-line purpose]"
---

# Subagent Scaffold

You are scaffolding a new subagent for the personal-assistant system. Subagents are specialist dispatch targets the root agent invokes per-wake (see `docs/ARCHITECTURE.md#agent-shape`). Every subagent has the same shape; this skill enforces that consistency.

**Scope check**: this skill is for *adding a new subagent to the repo during development*. It is NOT the runtime mechanism by which the root agent dispatches — that's done via NeMo Agent Toolkit config, not via this skill.

## Inputs

- **Name** — snake_case (e.g., `reading_agent`, `vault_organizer`). Must match the list in ARCHITECTURE.md or be a new addition to it.
- **Purpose** — one sentence: what triggers invoke this, what it produces.

If either is missing, interview the caller for them.

## Procedure

### 1. Confirm the subagent belongs

Read `docs/ARCHITECTURE.md#agent-shape`. The subagent must either be listed there (planned) or be a deliberate addition. If it's new:

- Propose adding it to the ARCHITECTURE list with a one-line description.
- Show the diff before writing.

### 2. Scaffold the source file

Create `agent/src/personal_assistant_agent/agents/<name>.py`. Follow the shape of the most recently-added sibling subagent (or, for the first one, use this skeleton):

```python
"""<Name> subagent: <one-sentence purpose>."""
from __future__ import annotations

from dataclasses import dataclass

# NeMo Agent Toolkit imports go here when the project is wired up;
# placeholder for now.


@dataclass(frozen=True)
class <Name>Inputs:
    """Structured input the root agent passes on dispatch."""
    trigger: str                # which wake trigger invoked this
    # additional fields specific to this subagent


def build() -> object:
    """Build and return the subagent instance for registration.

    Contract:
    - Reads from: <list the tools this subagent calls, e.g., vault_read, gmail_read>
    - Writes through: proposal_enqueue (never direct mutation)
    - Emits proposal action types: <list, e.g., vault_edit, email_label>
    - Escalates to user (via SMS or inbox note) when: <conditions>
    """
    raise NotImplementedError("<name> subagent not yet wired to NeMo")
```

### 3. Register the subagent

Update:
- `agent/src/personal_assistant_agent/agents/__init__.py` — export the builder
- `config/user.yaml.example` — add `<name>: true` under `subagents:` with a comment describing when to disable
- The root-agent registration site (when it exists): `agent/src/personal_assistant_agent/agents/root.py`

### 4. Add a test

Create `agent/tests/agents/test_<name>.py` with at minimum:

- A test that the builder returns without error once implemented
- A test that the subagent emits proposals (never direct writes) for representative inputs — this enforces the proposal-queue invariant

### 5. Update ARCHITECTURE.md if needed

If the subagent introduces new proposal action types, update:
- `docs/PROPOSAL_FORMAT.md` (registered action types table)
- The Go executor's validator + adapter (separate PR if out of scope)

### 6. Report

Summarize: name, purpose, tools read, proposal types emitted, tests added, config keys touched. Flag anything that still needs wiring (root-agent registration, NeMo config, executor adapters for new action types).

## Discipline

- **Every subagent uses `proposal_enqueue` for writes.** Never have a subagent call Gmail, Calendar, or write to the vault directly. The docstring's "Writes through" line must read exactly `proposal_enqueue`.
- **Every subagent documents its trigger conditions.** Which wake events invoke it? Without this, the root agent has no routing signal.
- **Every subagent documents its proposal action types.** Without this, PROPOSAL_FORMAT.md can't know what to validate.
- **One subagent = one responsibility.** If the proposed subagent reads from three unrelated sources and emits five action types, it's probably two subagents. Push back to the caller.
