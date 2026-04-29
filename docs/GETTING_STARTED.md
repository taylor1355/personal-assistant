# Getting Started

Setup guide for cloning the repo on a fresh machine, or moving an existing setup. Audience: developer. Non-technical onboarding is a separate flow that ships with v1+ and isn't covered here.

The repo runs on Windows / macOS / Linux. Commands are shown for Windows-with-Git-Bash first (the author's environment) with notes for the others.

## Prerequisites

| Tool | Minimum | Required when |
|---|---|---|
| `git` | any modern | always |
| `uv` | 0.x (recent) | always — manages Python env |
| Python | 3.13 | always (installed via `uv python install`) |
| Node.js + npm | 18+ | always — runs the Linear TS CLI |
| `gh` (GitHub CLI) | 2.0+ | needed for `gh auth login` so push/PR works without a PAT in your URL |
| Go | 1.23+ | only when touching `executor/`, `sync/`, `dispatcher/`, `sms/` (host-side services) |
| Docker Desktop | recent | only when running `docker compose` |

You only need Go and Docker once you start working on the host-side services or running the full system end-to-end. The Python agent + Linear tooling work without them.

## 1. Install the toolchain

### Windows (PowerShell, run as your user — UAC prompts handle elevation)

```powershell
# uv (no admin)
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"

# Python via uv (after uv is installed and on PATH)
uv python install 3.13

# Node.js LTS
winget install --id OpenJS.NodeJS.LTS --accept-source-agreements --accept-package-agreements

# GitHub CLI
winget install --id GitHub.cli --accept-source-agreements --accept-package-agreements

# Go (defer until you need it)
# winget install --id GoLang.Go --accept-source-agreements --accept-package-agreements

# Docker Desktop (defer until you need it; requires WSL2 + a reboot)
# winget install --id Docker.DockerDesktop --accept-source-agreements --accept-package-agreements
```

Open a fresh terminal so PATH picks up the new tools, then verify:

```powershell
git --version; uv --version; node --version; npm --version; gh --version
```

If `winget install` for `gh` reports an installer error, run the same command in an elevated PowerShell — the gh MSI requests admin via UAC, which doesn't propagate from a non-elevated session.

### macOS

```bash
# uv
curl -LsSf https://astral.sh/uv/install.sh | sh

# the rest, via Homebrew
brew install python@3.13 node gh
# brew install go         # when needed
# brew install --cask docker   # when needed

uv python install 3.13
```

### Linux (Debian/Ubuntu shown; adapt to your distro)

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
sudo apt update && sudo apt install -y nodejs npm
sudo apt install -y gh   # or follow https://cli.github.com/manual/installation
uv python install 3.13
```

## 2. Clone and authenticate

```bash
git clone https://github.com/taylor1355/personal-assistant.git
cd personal-assistant

gh auth login    # GitHub.com → HTTPS → authorize git → web browser flow
```

`gh auth login` configures git credentials for HTTPS, so subsequent `git push` Just Works.

## 3. Configure secrets and per-user settings

Two files are gitignored and need to live on each machine.

### `.env` — secrets and per-machine paths

```bash
cp .env.example .env
```

Then edit `.env`. Minimum keys to fill:

| Variable | Required for | How to obtain |
|---|---|---|
| `ANTHROPIC_API_KEY` | v0+ (LLM calls) | console.anthropic.com → API Keys |
| `LINEAR_API_KEY` | v1+ (Linear backbone) | Linear → Settings → API → Personal API keys → Create |
| `LINEAR_TEAM_KEY` | v1+ | defaults to `PA`; only change if you forked into a different team |
| `VAULT_PATH` | when sync runs | absolute path to your real Obsidian vault |
| `USER_TIMEZONE` | always | IANA name, e.g. `America/New_York` |

`.env.example` documents every variable. v0/v1 don't yet need Twilio, Google OAuth, or GitHub-PAT keys; those activate when their subsystems land.

### `.claude/settings.local.json` — per-user Claude Code permissions (optional)

Only relevant if you use Claude Code on this repo. Contains `additionalDirectories` (paths Claude is allowed to read outside the repo) and a Bash-allowlist for the local `uv` path. Either copy from another machine of yours, or let Claude Code regenerate it via permission prompts on first use.

### `config/user.yaml` and `config/providers.yaml` (later)

Not needed yet — v0/v1 read everything from `.env`. When `BUDGETER` and the dispatcher land, copy from `config/*.yaml.example` and edit.

## 4. Install dependencies

```bash
# Python: uv reads agent/pyproject.toml and creates agent/.venv
uv sync --project agent

# TypeScript Linear CLI: deps install on first invocation via npx --prefix
bash tools/linear whoami
```

`uv sync` takes ~1 minute on a clean install (it pulls NeMo Agent Toolkit + Anthropic SDK + LangChain bits). The Linear CLI install is a few seconds the first time, instant on subsequent runs.

If `bash tools/linear whoami` prints something like:

```
User:   <your name> <your email>
Team:   Personal Assistant (PA)
States: Triage, Backlog, Canceled, Todo, Done, Blocked, Duplicate, In Progress, In Review
Labels: agent, bug, devops, docs, ... track-build, track-use, urgent, vault-organization
```

…the chain is healthy: Node + npm + Linear API key + team are all wired.

## 5. Verify

```bash
# Full Python test suite — should be 85 passed
uv run --project agent pytest agent/tests -q

# Static analysis
uv run --project agent ruff check agent
uv run --project agent mypy agent/src

# Linear backlog
bash tools/linear status
```

The status command will list the v1 backlog (PA-1 through PA-20) seeded in [scripts/seed_v1_backlog.py](../scripts/seed_v1_backlog.py). If you forked into a fresh Linear team, run `bash tools/linear setup-labels` first to populate the label taxonomy, then `uv run --project agent python scripts/seed_v1_backlog.py` to seed the backlog.

## 6. First end-to-end run (v0 — journal completion detection)

The v0 capability is wake → read journal → detect completed todos → emit proposal. From a Bash-style shell:

```bash
ANTHROPIC_API_KEY=sk-ant-... \
  VAULT_ROOT="/path/to/your/Obsidian/vault" \
  PROPOSALS_PATH="./var/proposals" \
  USER_TIMEZONE="America/New_York" \
  uv run --project agent personal-assistant-agent wake --reason=journal
```

PowerShell equivalent:

```powershell
$env:VAULT_ROOT = "C:\Users\<you>\Documents\<your-vault>"
$env:PROPOSALS_PATH = "./var/proposals"
uv run --project agent personal-assistant-agent wake --reason=journal
```

The wake reads `01 - Journals/<year> Entries.md` from the vault, extracts today's section (heading `# M-DD`), reads `02 - Todos/01 - Short Term Todos.md`, calls Claude, and writes a proposal markdown file under `var/proposals/` for each todo it thinks is complete. With the executor still a stub, those proposals don't get applied — that's PA-3 in the backlog.

The inbox-flow equivalent (`wake --reason=inbox`) needs PA-1 to land first; it'll route to `intake_agent` and create Linear issues from your inbox dump.

## 7. Common operations

| What you want to do | Command |
|---|---|
| Look at the backlog | `bash tools/linear status` (overview), `bash tools/linear next` (top picks), `bash tools/linear blocked` (stuck) |
| Read an issue's detail | `bash tools/linear issue PA-N` |
| Create an issue from CLI | `bash tools/linear create "Title" --priority 3 --label feature --label agent --label track-build --state Backlog` |
| Pick up an issue (start work) | `bash tools/linear pickup PA-N` |
| Mark an issue done | `bash tools/linear done PA-N` |
| Add a blocker relation | `bash tools/linear link PA-blocker PA-blocked` |
| Run a single test file | `uv run --project agent pytest agent/tests/test_<x>.py -v` |
| Find an existing helper before adding a new one | use the `pattern-auditor` agent (see `.claude/agents/`) |

## 8. Where to find what

| Topic | Document |
|---|---|
| Overall architecture, capability tiers | [ARCHITECTURE.md](ARCHITECTURE.md) |
| Project-specific architectural rules | [.claude/rules/architecture.md](../.claude/rules/architecture.md) |
| Code style + dev patterns | [.claude/rules/development-patterns.md](../.claude/rules/development-patterns.md) |
| Testing conventions | [.claude/rules/testing.md](../.claude/rules/testing.md) |
| Proposal file format | [PROPOSAL_FORMAT.md](PROPOSAL_FORMAT.md) |
| Token budget rules | [BUDGET.md](BUDGET.md) |
| Linear labels, priorities, templates | [LINEAR_CONVENTIONS.md](LINEAR_CONVENTIONS.md) |
| Vault organization (frontmatter, Bases) | [VAULT_ORGANIZATION.md](VAULT_ORGANIZATION.md) |
| v2 dev-work capability | [DEVOPS.md](DEVOPS.md) |
| Single-page index | [../CLAUDE.md](../CLAUDE.md) |

## Migrating from another machine

Same as a fresh install above, with two shortcuts:

1. Copy `.env` from the old machine instead of editing `.env.example`. Update `VAULT_PATH` if the vault is at a different path.
2. Optionally copy `.claude/settings.local.json` for the same Claude Code permissions; the `uv.exe` path inside may need updating.

Everything else (`agent/.venv/`, `tools/linear-pm/node_modules/`, `__pycache__/`) regenerates on first sync. Don't bother transferring those — they're machine-specific and recreated by `uv sync` and the first `tools/linear` invocation.

## Troubleshooting

| Symptom | Likely cause / fix |
|---|---|
| `uv: command not found` | uv not on PATH; open a fresh terminal after install. On Windows the installer puts it in `%USERPROFILE%\.local\bin\`. |
| `LINEAR_API_KEY not found` | `.env` missing or key not set; copy `.env.example` and fill in. |
| `Error: program not found: npx` (Python wrapper) | Node not installed or not on PATH; install per step 1 and reopen the shell. |
| `pytest` "FileNotFoundError" creating dir under `tmp_path` | not seen in current main; if it returns, file an issue with `bug` label. |
| `ruff` complains after pulling latest | `uv sync --project agent` to pick up any new dev deps. |
| Linear `whoami` reports "Team … not found" | `LINEAR_TEAM_KEY` in `.env` doesn't match an existing team; check the value and team key in Linear's UI. |
| Hooks/permissions prompt floods Claude Code | re-create `.claude/settings.local.json` from another machine, or grant permissions inline once. |
