# Testing Rules

Adapted from `taylor1355/npc-simulation/.claude/rules/testing.md`. The principles transfer directly; specific helpers and frameworks are project-specific.

## Quick Start

```bash
# All tests, single command
uv run --project agent pytest agent/tests -v

# One file
uv run --project agent pytest agent/tests/test_linear_cli.py -v

# One test
uv run --project agent pytest agent/tests/test_root.py::test_handle_wake_emits_proposals -v

# Save output for grep
uv run --project agent pytest agent/tests 2>&1 | tee /tmp/pytest.txt
grep -E "FAIL|ERROR" /tmp/pytest.txt
```

Go service tests:

```bash
cd executor && go test ./... -v -count=1
```

Python suite must finish in < 5s; if it slows down, that's a signal — the codebase is dragging in expensive deps somewhere or a test is hitting a real network. Investigate.

## Static Analysis Before Commit

```bash
uv run --project agent ruff check agent
uv run --project agent mypy agent/src
cd executor && go vet ./...
```

The `code-quality` agent does all four in `fix-loop` mode and surfaces what to fix. Don't commit with new lint errors — the `pr` skill will block at Phase 1 anyway.

## Test File Conventions

- **Path**: `agent/tests/test_<subject>.py` — flat directory, mirrors `agent/src/personal_assistant_agent/<subject>.py`. Don't reproduce the package's nested folder structure unless tests would otherwise collide.
- **Function naming**: `test_<subject>_<behavior>_<condition>`. Read the name aloud and it should describe what's verified.
- **Fixtures**: `@pytest.fixture` in the same file when used by ≤2 tests; `conftest.py` for ones reused across files.
- **Async**: `pytest.mark.asyncio` (configured); `pytest-asyncio` is in the dev group.

```python
# Good test name
def test_extract_journal_section_returns_empty_when_date_absent(): ...

# Bad — what is being tested?
def test_journal(): ...
```

## Test Quality

Every test must have **regression value** — it would fail if the behavior it documents changes. Before writing a test, ask: "What future code change would make this fail?" If nothing realistic, the test is tautological and wastes test space.

### Tautological patterns to avoid

- Asserting `x == x` via two variable names
- Asserting `f(a) == f(a)` (function purity isn't usually what you're testing)
- Asserting a constant equals itself across two lookups
- Tests that pass with any constant values (the assertion doesn't constrain anything)

### What good tests look like

- **Constraint tests**: outputs stay within design bounds (`assert 0 < cost < 0.10`)
- **Relationship tests**: two independent computations have the expected relation (`assert proposal_a.proposed_at < proposal_b.proposed_at`)
- **Behavioral tests**: known input → expected output through real production code
- **Regression tests**: the specific buggy condition no longer produces the buggy result

### Closed-schema tests

For any Pydantic model with `extra="forbid"`, include a test that asserts an unknown key raises `ValidationError`. The schema is the contract; the test proves the contract is enforced.

## Mocking Discipline

Mock at process boundaries, not inside your own code:

- **Subprocess**: replace `subprocess.run` via `monkeypatch`. `LinearClient` tests do this; copy the pattern.
- **LLM**: pass a fake client into the function under test (constructor injection); never patch `anthropic.Anthropic` globally.
- **Filesystem**: use `tmp_path` fixture; never write to the real vault from a test.
- **Time**: take `now: datetime` as an explicit argument where time matters; don't `monkeypatch.setattr(datetime, ...)`.

If you find yourself wanting to mock something inside the package being tested, that's a design signal: the function probably has too many responsibilities or its dependencies should be injected.

### Don't mock the proposal-queue invariant

If a test needs to mock `proposal_enqueue` to avoid actually emitting proposals, two questions:

1. Is the test exercising too much? Test the smaller unit instead.
2. Does the production code call `proposal_enqueue` from the wrong layer? The invariant is "agent emits proposals"; sub-functions should return data the caller emits, not emit themselves.

The fix is almost always to refactor production code, not to add a mock.

## Regression Tests for Bug Fixes

When fixing a bug found in review or production, **write the regression test first**:

1. Write a test that reproduces the bug; it fails against current code
2. Apply the fix; verify the test passes
3. Both land in the same commit

Reasons:
- The bug is *actually* fixed (not coincidentally fixed)
- The bug can't silently reappear during refactoring
- Reviewers can verify the fix by reading the test

Record the regression-test decision in the commit body. If you choose NOT to add one (e.g., the bug is a one-liner caught by any consumer test), explain why.

## Cross-Language Roundtrip Tests

Where Python writes data Go reads (or vice versa), include a roundtrip test:

```python
# Encode in Python
proposal_md = proposal.to_markdown()

# Decode in Go-equivalent code
parsed = parse_proposal_markdown(proposal_md)

# Round-trips preserve the data
assert parsed == proposal
```

The Go-side test (when it exists) goes the other direction. These catch encoding mismatches at the schema level, not after the agent has written 50 corrupted files.

For the Linear CLI: smoke-test reads against a real (test) workspace. Don't try to mock the entire `@linear/sdk` — too brittle.

## Pre-existing Failures

When a test fails for reasons unrelated to your change:

1. Don't ignore it
2. Don't paper over it (skip, broaden tolerance, comment it out)
3. Create a Linear issue with the `bug` label and (when known) a subsystem label
4. Continue with your original work; reference the issue in your commit if relevant

The latent test bug fixed in commit 8c90d09 (`_make_vault` missing `parents=True`) is exactly this scenario — it didn't surface until the full suite was run on a clean checkout, then we fixed it as a small piece of the linear-cli wrapper commit.

## What's Worth Testing vs. Not

**Always test:**
- Schema validation (closed-schema, type errors, value constraints)
- Cross-language contracts (proposal roundtrip, CLI argument shape)
- The proposal-queue invariant (no direct mutations from agent code paths)
- Regression cases for fixed bugs
- Branching logic in subagents (what triggers route here, what gets emitted)
- Error handling: does the right exception type surface?

**Don't bother testing:**
- Trivial getters/setters (Pydantic generates them; use the model)
- Pure formatting that's covered by an integration test
- LLM output content (use deterministic test input → check structural shape, not text)
- Third-party libraries (Pydantic, Linear SDK, Anthropic SDK don't need our tests)

When you're unsure, the question isn't "could this break?" — everything could. It's "if it broke, would no other test catch it?" If yes, write the test; if no, skip.

## Testing Checklist for New Subagents

When `subagent-scaffold` generates a new subagent file, the test file should include at minimum:

1. **Happy path**: representative input → expected proposal(s) emitted
2. **Empty input**: nothing to act on → no proposals, no LLM call (use an exploding fake client to assert)
3. **Phantom output**: LLM returns content that doesn't match production state → silently skipped, no false proposal
4. **Boundary cases**: timezone edges, empty strings, missing optional fields
5. **Error path**: LLM call fails → wake exits cleanly, session log records the failure

Five tests is the floor. Real subagents grow more as they accumulate edge cases.
