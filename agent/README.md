# agent

Python agent core for `personal-assistant`, built on the NVIDIA NeMo Agent Toolkit.

## Running

From the repo root:

```bash
# One-time: install deps into a uv-managed venv.
uv sync --project agent

# Manual wake (v0 only entrypoint).
uv run --project agent personal-assistant-agent wake --reason=manual-test
```

Or via compose:

```bash
docker compose run --rm agent wake --reason=manual-test
```

## Layout

```
src/personal_assistant_agent/
  cli.py          # typer app — `wake` is the v0 entrypoint
  agents/         # root + subagent definitions  (coming next)
  tools/          # proposal_enqueue, vault_read (coming next)
  providers/      # provider abstraction over Anthropic / OpenRouter / Ollama (later)
```

See [../docs/ARCHITECTURE.md](../docs/ARCHITECTURE.md) for the full design.
