# pa_mcp — Personal Assistant tools for the Hermes harness (v0)

Exposes the PA value layer (vault reads + Linear board/planning) to the
[Hermes Agent](https://github.com/nousresearch/hermes-agent) harness over MCP.
This keeps Hermes an unmodified upstream clone — PA code lives here and reaches
it as the `mcp-pa-tools` toolset. Reuses `read_vault_file` + `LinearClient`
from `agent/` (loaded via importlib, so no NeMo dependency).

See `docs/ARCHITECTURE.md` for how this fits the pivot; the proposal-queue
invariant is enforced by **toolset lockdown** — the orchestrator is given only
`mcp-pa-tools` (+ skills/memory), never Hermes' `terminal`/`file` toolsets, so
it cannot mutate user state outside these typed tools.

## Tools (12)

`vault_read`, `vault_list` · `linear_board`, `linear_todo`, `linear_next`,
`linear_issue`, `linear_search` (reads) · `linear_create`, `linear_comment`,
`linear_set_state`, `linear_set_priority`, `linear_link` (planning writes).

## Dev setup

```bash
cd pa_mcp
uv venv --python 3.11
uv pip install mcp
```

Hermes launches the server over stdio. Required env (set in the Hermes config):

- `PA_REPO_ROOT` — a PA checkout containing `tools/linear-pm` + `.env` (Linear creds)
- `VAULT_ROOT` — the Obsidian vault root (read-only access)

Wiring check (no Hermes needed):

```bash
PA_REPO_ROOT=<repo> VAULT_ROOT=<vault> .venv/Scripts/python.exe \
  -c "import pa_tools_server; print('ok')"
```

## Hermes wiring

> On Windows, `HERMES_HOME` is `%LOCALAPPDATA%\hermes` (not `~/.hermes`).
> Hermes also needs its MCP **client**: `uv pip install -e ".[mcp]"` in the clone.

Set the local provider (writes the active config — a hand-edited `model:` block
does not register):

```bash
hermes config set model.provider custom
hermes config set model.base_url http://localhost:11434/v1
hermes config set model.default gpt-oss:20b
hermes config set model.api_key ollama          # Ollama ignores it; SDK needs non-empty
```

Then add to that same `config.yaml`:

```yaml
mcp_servers:
  pa-tools:
    command: "<abs path>/pa_mcp/.venv/Scripts/python.exe"
    args: ["<abs path>/pa_mcp/pa_tools_server.py"]
    env:
      PA_REPO_ROOT: "<repo>"
      VAULT_ROOT: "<vault>"
    timeout: 60
platform_toolsets:
  cli: [mcp-pa-tools, skills, memory]            # lockdown: read + plan only
```

Verify and run:

```bash
hermes mcp test pa-tools                          # -> Connected / 12 tools
hermes --ignore-rules -z "brief me on my vault and Linear board"
```
