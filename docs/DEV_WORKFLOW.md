# Development Workflow

How dev work flows from a Linear issue to a merged PR, and how issue status stays
current without manual bookkeeping.

## The lifecycle

Every dev issue moves `Todo → In Progress → Done`. Three mechanisms keep that
status accurate so you rarely touch it by hand:

| Transition | Driver | When |
|---|---|---|
| `Todo → In Progress` | `/work` orchestrator (`tools/linear pickup`) **and** the Linear↔GitHub integration | On dispatch, or when a branch/PR first references the issue |
| `In Progress → Done` | Linear↔GitHub integration | When the issue's PR merges (`Fixes PA-<id>` in the PR body) |
| `In Progress → Todo` | Daily stale-revert job | Issue idle beyond the window (default 7 days) with no open PR/branch |

The done-on-merge path runs through Linear's GitHub integration, **not** a `/work`
session — so a PR you merge by hand still closes its issue.

Manual overrides always win: if you move an issue yourself, nothing fights you.

> The `Todo → In Progress` and `In Progress → Done` transitions are live once the
> integration below is connected. The stale-revert job (`tools/linear stale-revert`)
> ships in a follow-up (PA-106, PR 1b).

## One-time setup: connect Linear ↔ GitHub

*(Done once, and only you can authorize it.)*

1. In Linear: **Settings → Features → Integrations → GitHub → Connect**. Authorize
   the GitHub account/org and grant access to the **`taylor1355/personal-assistant`**
   repo.
2. In the GitHub integration settings, enable PR linking and the state automation:
   - **Link pull requests to issues** (by branch name and by magic words).
   - **PR opened →** move the linked issue to **In Progress**.
   - **PR merged →** move the linked issue to **Done**.
   Exact wording varies by Linear version; the mapping you want is
   "PR opened → In Progress" and "PR merged → Done".
3. Confirm the **Personal Assistant (PA)** team is selected so `PA-<id>` ids resolve.

### Verify it works

1. Branch off main for any small throwaway issue: `feature/PA-<id>-verify-linear`.
2. Open a PR whose body contains `Fixes PA-<id>`. → the issue flips to **In Progress**
   and shows the linked PR.
3. Merge (or close) the PR. → the issue flips to **Done**.

If a transition doesn't fire, re-check step 2's automation mapping and that the PR
body actually contains `Fixes PA-<id>` (or the branch name contains `PA-<id>`).

## Using it day to day

- **Branch naming**: `<type>/PA-<id>-<slug>`, e.g. `feature/PA-100-nudge-engine`.
  The `PA-<id>` in the branch is enough for Linear to link the PR.
- **PR body**: include `Fixes PA-<id>` — the `/pr` skill adds this automatically.
  `Fixes` / `Closes` / `Resolves` all trigger done-on-merge; `Ref` / `Part of`
  link without closing.
- **Several issues in one PR**: add one `Fixes PA-<id>` line per issue.
- **Parallel work**: the `/work` skill dispatches issues into isolated worktrees and
  owns pickup + delivery. See [.claude/skills/work/SKILL.md](../.claude/skills/work/SKILL.md).

## What still needs a human

- Connecting the integration (above).
- Merging PRs — the merge is the approval gate; `gh pr merge` is intentionally not
  automated.
- Strategic Linear changes — priority, labels, project, triage.
