# tools/

Host-side developer tooling. The Linear CLI (`linear` + `linear-pm/`) is documented
in [../docs/LINEAR_CONVENTIONS.md](../docs/LINEAR_CONVENTIONS.md). The scripts below
support the `/work` orchestrator ([../.claude/skills/work/SKILL.md](../.claude/skills/work/SKILL.md)).

| Script | Purpose |
|---|---|
| `preflight_dispatch.sh` | Phase 0 gate: verifies the shared toolchain (git, gh, uv, node, go), Linear reachability, worktree bootstrap state, and that the unit suite runs. Exit 0 = green, 1 = red. Run before dispatching. |
| `setup_worktree.sh` | Bootstraps a fresh worktree to a test-runnable state: copies `.env` from a sibling worktree, `uv sync`s `agent/.venv`, and `npm install`s the Linear CLI deps. Idempotent. `--check` reports state without doing work. |
| `check_prs.sh` | Walks the FULL reviewer-comment history for one or more PRs and reports per-comment disposition (`[OPEN]` / `[DISPOSITIONED]`). No `--since` filtering, so "no OPEN entries" is a real signal, not a filter artifact. |
| `watch_pr_merges.sh` | Emits one `MERGED #<n> [<branch>] <title>` line per PR merge, for wrapping in the `Monitor` tool (Phase 6b merge watcher). |
| `check_pr_cascade.sh` (+ `.py`) | Given a just-merged PR and the open PR set, shortlists open PRs whose reviewer feedback references files the merge touched (cross-PR cascade). A shortlist generator — manual review is the gate. |

`check_prs.sh`, `watch_pr_merges.sh`, and `check_pr_cascade.*` are ported from
npc-simulation; internal `NPC-xxx` references are original provenance (npc-simulation
issue ids documenting why the code is shaped that way, not personal-assistant ids).

## One-time prerequisites (merge watcher only)

`watch_pr_merges.sh` needs, once per machine:

```bash
gh extension install cli/gh-webhook     # event stream for PR merges
winget install jqlang.jq                # standalone jq (the webhook pipe uses it)
```

The other scripts use `gh`'s bundled jq and need no extra install. `check_pr_cascade.*`
uses the project's uv-managed Python when no standalone `python3` is present.
