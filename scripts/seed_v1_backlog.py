"""One-shot script that seeds the PA Linear team with the v1 backlog.

Run once with:

    uv run --project agent python scripts/seed_v1_backlog.py

NOT idempotent — re-running will create duplicates. The script lives in
the repo as a record of how the initial backlog was structured; it is
not part of the normal workflow.
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "agent" / "src"))


def _load_env(path: Path) -> None:
    """Minimal KEY=VALUE loader so the script works without python-dotenv."""
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


_load_env(REPO_ROOT / ".env")

from personal_assistant_agent.tools.linear_cli import LinearClient  # noqa: E402

# Each issue: a key (used for cross-referencing in BLOCKS), the create
# parameters, and an optional list of Blocks pointing at other keys.
# Order is creation order; PA identifiers fall in this order.

ISSUES: list[dict] = [
    {
        "key": "wire-cli",
        "title": "Wire `wake --reason=inbox` to construct LinearClient",
        "description": (
            "## Outcome\n"
            "`personal-assistant-agent wake --reason=inbox` against a populated "
            "`00 - Assistant/Inbox.md` creates Linear issues end-to-end without "
            "additional code changes.\n\n"
            "## Notes\n"
            "`handle_wake` already accepts a `linear=...` argument; this is "
            "wiring it through `cli.py`. Source: `agent/src/personal_assistant_agent/cli.py`."
        ),
        "type_label": "feature",
        "subsystem": "agent",
        "track": "track-build",
        "priority": 2,
    },
    {
        "key": "smoke-test",
        "title": "Manual end-to-end smoke test of inbox → Linear flow",
        "description": (
            "## Outcome\n"
            "Confidence the inbox loop works on real content; any prompt fixes "
            "to `intake_agent` shipped.\n\n"
            "## Notes\n"
            "v1 daily-use validation gate. Populate `00 - Assistant/Inbox.md` "
            "with 5–10 representative dumps, run wake, verify created issues "
            "have sensible labels and priorities. Iterate on `intake_agent` "
            "system prompt if classifications miss."
        ),
        "type_label": "investigation",
        "subsystem": "agent",
        "track": "track-build",
        "priority": 2,
    },
    {
        "key": "executor",
        "title": "Implement real Go executor (replace stub)",
        "description": (
            "## Outcome\n"
            "A pending proposal manually flipped to `approved` is validated, "
            "applied to the agent's vault copy via the typed adapter, and "
            "transitioned to `applied` (or `failed`) with an audit entry.\n\n"
            "## Acceptance criteria\n"
            "- Watches `PROPOSALS_PATH` for proposal files (fsnotify)\n"
            "- Validates against the same schema as `proposal_enqueue` "
            "(closed schema, registered actions, target shape)\n"
            "- Adapters for: vault_edit (mode=diff and replace), vault_create, "
            "vault_delete (move to `00 - Assistant/Trash/`)\n"
            "- Audit log appended to `var/executor/audit.log`\n"
            "- Applied proposals moved to `00 - Assistant/Proposals/Applied/YYYY-MM/`\n\n"
            "## Notes\n"
            "Calendar/email adapters can be deferred to PA-14. See "
            "`docs/PROPOSAL_FORMAT.md` and `docs/ARCHITECTURE.md#the-proposal-queue`."
        ),
        "type_label": "feature",
        "subsystem": "executor",
        "track": "track-build",
        "strategic": ["keystone"],
        "priority": 2,
    },
    {
        "key": "dispatcher",
        "title": "Implement Go dispatcher (debounced trigger batcher)",
        "description": (
            "## Outcome\n"
            "Three quick edits to `00 - Assistant/Inbox.md` within the quiet "
            "window result in exactly one wake invocation after 5 min of quiet "
            "(or 15 min total since first event).\n\n"
            "## Acceptance criteria\n"
            "- Per-source debounce: quiet 5min, max-delay 15min, max-buffer 10\n"
            "- File-watch trigger source (Inbox), webhook receiver, cron\n"
            "- Invokes `personal-assistant-agent wake --reason=<source> --payload <json>`\n"
            "- Config keys live under `triggers:` in `config/user.yaml`\n\n"
            "## Notes\n"
            "See `docs/ARCHITECTURE.md#debounced-dispatcher`. Use fsnotify."
        ),
        "type_label": "feature",
        "subsystem": "dispatcher",
        "track": "track-build",
        "priority": 2,
    },
    {
        "key": "pm-agent",
        "title": "Build pm_agent (daily Linear triage subagent)",
        "description": (
            "## Outcome\n"
            "Issues that `intake_agent` leaves in Triage get promoted to "
            "Backlog/Todo with proper labels via a single morning approval.\n\n"
            "## Acceptance criteria\n"
            "- Pulls Triage-state issues via LinearClient\n"
            "- Per issue: classify type label, suggest priority, suggest "
            "target state\n"
            "- Emits ONE user-gated proposal with the full triage batch (per "
            "`docs/LINEAR_CONVENTIONS.md`)\n"
            "- User approves/rejects/edits collectively\n\n"
            "## Notes\n"
            "All Linear ops via LinearClient; proposal via `proposal_enqueue`."
        ),
        "type_label": "feature",
        "subsystem": "agent",
        "track": "track-build",
        "priority": 3,
    },
    {
        "key": "budgeter",
        "title": "Implement Budgeter + spend ledger",
        "description": (
            "## Outcome\n"
            "An LLM call that would breach the daily hard cap raises "
            "BudgetExceeded; the wake catches at root, writes a session-log "
            "entry explaining what was skipped, and exits cleanly.\n\n"
            "## Acceptance criteria\n"
            "- Daily hard $10, weekly hard $30, daily soft $3, tier-3 baseline $1/d\n"
            "- Per-call estimate; check caps in order; record actual to "
            "`var/agent/spend.jsonl`\n"
            "- Daily/weekly windows in user's timezone\n"
            "- Session log includes a budget summary block\n\n"
            "## Notes\n"
            "See `docs/BUDGET.md`."
        ),
        "type_label": "feature",
        "subsystem": "agent",
        "track": "track-build",
        "priority": 3,
    },
    {
        "key": "pr-reviewer",
        "title": "Port automated PR reviewer from npc-simulation",
        "description": (
            "## Outcome\n"
            "Opening a PR triggers an LLM review comment within ~1 minute; "
            "flags proposal-queue bypass, write-creds-in-container, and other "
            "anti-patterns from `.claude/rules/architecture.md` as critical "
            "findings.\n\n"
            "## Notes\n"
            "Source: `npc-simulation/.github/workflows/`. Adapt for Python/Go "
            "diffs (was GDScript). May need a Gemini API key in repo secrets. "
            "Initial scope: this repo only; multi-repo via PA-17 (devops)."
        ),
        "type_label": "feature",
        "subsystem": "infra",
        "track": "track-build",
        "priority": 3,
    },
    {
        "key": "sync-daemon",
        "title": "Implement Go sync daemon (replace stub)",
        "description": (
            "## Outcome\n"
            "Edit a file in real vault → change appears in agent's copy within "
            "the debounce window. Agent writes inside `00 - Assistant/` in its "
            "copy → change appears in user's vault.\n\n"
            "## Acceptance criteria\n"
            "- Two-way sync between `VAULT_PATH` (real) and `VAULT_COPY_PATH` "
            "(agent's mount)\n"
            "- Debounced; conflict resolution by timestamp + dated backup of "
            "the losing side\n"
            "- Outside `00 - Assistant/`, sync is read-from-user-only "
            "(executor handles writes)\n"
            "- Explicit ignore list (`.git`, `.obsidian/.cache`, etc.)\n\n"
            "## Notes\n"
            "Blocked by PA-3: agent's writes inside `00 - Assistant/` go via "
            "executor, which sync round-trips back to the user's vault."
        ),
        "type_label": "feature",
        "subsystem": "sync",
        "track": "track-build",
        "priority": 2,
    },
    {
        "key": "intake-vault",
        "title": "Wire vault-bound intake branches (journal/plan/todo/calendar)",
        "description": (
            "## Outcome\n"
            "A journal-style inbox dump produces a `vault_edit` proposal "
            "appending to `01 - Journals/{year} Entries.md` under today's "
            "section; analogous handling for plan/todo/calendar items.\n\n"
            "## Acceptance criteria\n"
            "- Branch per kind: journal_entry, plan, vault_todo, calendar_item\n"
            "- Each emits the appropriate proposal action type\n"
            "- Slug naming and proposal body shape per branch\n\n"
            "## Notes\n"
            "Blocked by PA-3: executor needs to handle these action types. "
            "Calendar adapter ships in PA-14."
        ),
        "type_label": "feature",
        "subsystem": "agent",
        "track": "track-build",
        "priority": 3,
    },
    {
        "key": "vault-organizer",
        "title": "vault_organizer subagent — frontmatter + Bases proposal pipeline",
        "description": (
            "## Outcome\n"
            "A `vault_organizer` wake on `02 - Todos/` proposes frontmatter "
            "additions for ~5 todo files, following the schema in "
            "`docs/VAULT_ORGANIZATION.md`.\n\n"
            "## Acceptance criteria\n"
            "- Per-wake scope: one folder family\n"
            "- Schema-before-content discipline (proposes `00 - Assistant/Schemas/<folder>.yaml` "
            "before backfilling)\n"
            "- Triggered by inbox commands (\"organize my X notes\") and by "
            "scheduled tier-2/3 wakes\n"
            "- Creates Bases views (`.base` files) for the active schema\n\n"
            "## Notes\n"
            "Blocked by PA-3 (vault writes via executor). Builds on PA-18 schemas."
        ),
        "type_label": "feature",
        "subsystem": "agent",
        "track": "track-build",
        "priority": 3,
    },
    {
        "key": "linear-audit",
        "title": "linear_agent — emit audit-log proposals for auto-applied Linear ops",
        "description": (
            "## Outcome\n"
            "Every Linear op the agent performs leaves a markdown trace in "
            "`00 - Assistant/Proposals/Applied/`.\n\n"
            "## Acceptance criteria\n"
            "- Wraps LinearClient calls in a `linear_agent` interface\n"
            "- Emits a proposal with `status: applied` and the op result\n"
            "- New action type (`linear_audit` or similar) handled by executor "
            "as no-op-with-log\n\n"
            "## Notes\n"
            "Blocked by PA-3 (executor needs to recognize the action type)."
        ),
        "type_label": "feature",
        "subsystem": "agent",
        "track": "track-build",
        "priority": 3,
    },
    {
        "key": "daily-digest",
        "title": "Daily digest subagent + scheduled trigger",
        "description": (
            "## Outcome\n"
            "Daily file appears in `00 - Assistant/Digest/YYYY-MM-DD.md` each "
            "morning, summarizing yesterday's processed inbox, today's calendar, "
            "upcoming dated plans, top backlog items, and items ripe for review.\n\n"
            "## Notes\n"
            "Blocked by PA-4 (scheduled trigger). Reads Linear `next` + Calendar "
            "+ journal; writes via `vault_create` proposal."
        ),
        "type_label": "feature",
        "subsystem": "agent",
        "track": "track-build",
        "priority": 3,
    },
    {
        "key": "sms-bridge",
        "title": "SMS bridge (Twilio webhook + outbound)",
        "description": (
            "## Outcome\n"
            "Texting your Twilio number causes a wake within seconds; agent "
            "replies via SMS.\n\n"
            "## Acceptance criteria\n"
            "- New service under `sms/`\n"
            "- Twilio signature validation on inbound\n"
            "- Forwards to dispatcher with `reason=sms_inbound`\n"
            "- Outbound REST sender for `sms_send` tool\n"
            "- Cloudflare Tunnel for the public webhook URL\n\n"
            "## Notes\n"
            "Blocked by PA-4 (dispatcher routes the trigger). Holds Twilio "
            "creds in `.env` on host."
        ),
        "type_label": "feature",
        "subsystem": "sms",
        "track": "track-build",
        "priority": 3,
    },
    {
        "key": "calendar-gmail",
        "title": "Calendar + Gmail read integration (OAuth)",
        "description": (
            "## Outcome\n"
            "The agent can answer \"what's on my calendar this week?\" and "
            "\"summarize my last 5 emails\" without write access.\n\n"
            "## Acceptance criteria\n"
            "- One-time OAuth dance via a separate setup script\n"
            "- Refresh token in `.env`\n"
            "- `calendar_read` tool: list events for date range\n"
            "- `gmail_read` tool: list/get messages with filters\n"
            "- Read-only scopes only\n\n"
            "## Notes\n"
            "Powers calendar_agent and email_agent (separate issues). Adds "
            "calendar adapter to executor for `calendar_create` (write side)."
        ),
        "type_label": "feature",
        "subsystem": "agent",
        "track": "track-build",
        "priority": 3,
    },
    {
        "key": "research-agent",
        "title": "research_agent with web_search tool",
        "description": (
            "## Outcome\n"
            "An issue \"research X\" gets picked up; agent does multi-step "
            "research; lands a synthesis note via `vault_create` proposal; "
            "comments on the Linear issue with a link.\n\n"
            "## Acceptance criteria\n"
            "- Picks up `research`-typed issues in Todo\n"
            "- `web_search` tool (Tavily or similar)\n"
            "- Time-boxed; respects per-issue time budget if set\n"
            "- Output: `00 - Assistant/Research/<topic>.md`\n\n"
            "## Notes\n"
            "Tier-2/3 work; ranked alongside other backlog items by the root."
        ),
        "type_label": "feature",
        "subsystem": "agent",
        "track": "track-build",
        "priority": 3,
    },
    {
        "key": "goodreads",
        "title": "Goodreads sync (reading_agent)",
        "description": (
            "## Outcome\n"
            "Adding a book on Goodreads results in a proposal to add it to the "
            "vault reading list.\n\n"
            "## Notes\n"
            "Goodreads has limited public API; RSS is the typical workaround. "
            "Idempotent: tracks last-synced state."
        ),
        "type_label": "feature",
        "subsystem": "agent",
        "track": "track-build",
        "priority": 4,
    },
    {
        "key": "devops",
        "title": "devops service: GitHub PR submission (v2)",
        "description": (
            "## Outcome\n"
            "Agent picks up a code-typed Linear issue with `repo:` label, "
            "ships a PR for user review.\n\n"
            "## Acceptance criteria\n"
            "- New host-side service under `devops/`\n"
            "- Constrained by `GITHUB_ALLOWED_REPOS`\n"
            "- Worktree per issue; runs tests on host before PR\n"
            "- Self-PR safety rules per `docs/DEVOPS.md`\n\n"
            "## Notes\n"
            "v2; defer until v1 is stable and a real backlog of code issues "
            "exists."
        ),
        "type_label": "feature",
        "subsystem": "devops",
        "track": "track-build",
        "priority": 4,
    },
    {
        "key": "vault-schemas",
        "title": "Vault organization: design frontmatter schemas per folder type",
        "description": (
            "## Outcome\n"
            "User-approved frontmatter schemas committed as "
            "`00 - Assistant/Schemas/<folder>.yaml`, ready for migration via "
            "PA-10 (vault_organizer).\n\n"
            "## Notes\n"
            "Blocked by PA-20 (folder-structure overhaul) — schemas depend on "
            "what folders exist. Initial focus: `02 - Todos/`, "
            "`04 - Plans/Dated/`, `03 - Personal Projects/<project>/`. See "
            "`docs/VAULT_ORGANIZATION.md` for starter schemas."
        ),
        "type_label": "vault-organization",
        "subsystem": None,
        "track": "track-use",
        "strategic": ["keystone"],
        "priority": 2,
    },
    {
        "key": "bases-views",
        "title": "Set up Bases views for the v1 starter view library",
        "description": (
            "## Outcome\n"
            "Opening `00 - Assistant/Views/` in Obsidian shows live, filterable "
            "views over actual vault content.\n\n"
            "## Acceptance criteria\n"
            "- Views: Active Todos, Done This Week, Upcoming Plans, Active "
            "Projects, Stale Notes, Reading In Progress\n"
            "- Each `.base` lives in `00 - Assistant/Views/`\n"
            "- Each carries a one-paragraph header explaining its purpose\n\n"
            "## Notes\n"
            "Blocked by PA-18 (frontmatter schemas)."
        ),
        "type_label": "vault-organization",
        "subsystem": None,
        "track": "track-use",
        "priority": 3,
    },
    {
        "key": "vault-overhaul",
        "title": "Overhaul the organizational structure of the Obsidian vault (collaborative)",
        "description": (
            "## Outcome\n"
            "A new folder layout proposed and applied; old structure migrated; "
            "user comfortable with the new shape.\n\n"
            "## Notes\n"
            "Long-running collaborative work, not a single sit-down — likely "
            "weeks of iteration. The current PARA-like numbered scheme has "
            "accumulated cruft (overlapping todo horizons, vestigial daily/"
            "weekly tracking, scattered Claude notes). Sub-issues spin off as "
            "the work progresses (one per folder/cluster being reorganized). "
            "Settles the structure that PA-18 schemas will be designed against."
        ),
        "type_label": "vault-organization",
        "subsystem": None,
        "track": "track-use",
        "strategic": ["keystone"],
        "priority": 2,
    },
]


# (blocker_key, blocked_key) — applied via `tools/linear link` after creation.
BLOCKS: list[tuple[str, str]] = [
    ("wire-cli", "smoke-test"),
    ("executor", "sync-daemon"),
    ("executor", "intake-vault"),
    ("executor", "vault-organizer"),
    ("executor", "linear-audit"),
    ("dispatcher", "daily-digest"),
    ("dispatcher", "sms-bridge"),
    ("vault-overhaul", "vault-schemas"),
    ("vault-schemas", "bases-views"),
]


_CREATED_RE = re.compile(r"^Created (\S+):", re.MULTILINE)


_SEARCH_LINE_RE = re.compile(r"^\s+(\S+)\s+\[[^\]]*\]:\s+(.*)$")


def _existing_by_title(linear: LinearClient) -> dict[str, str]:
    """Return ``{title: identifier}`` for everything matching our titles.

    The CLI's `search` accepts a title fragment; we run it once per a
    short distinctive substring per issue, then map results back. Cheaper
    than scanning the whole team.
    """
    found: dict[str, str] = {}
    for issue in ISSUES:
        # Use a distinctive substring of the title — first 3 words usually
        # unique and avoids weird-character search-encoding issues.
        token = " ".join(issue["title"].split()[:3])
        try:
            out = linear.search(token)
        except Exception:
            continue
        for line in out.splitlines():
            m = _SEARCH_LINE_RE.match(line)
            if not m:
                continue
            ident, found_title = m.group(1), m.group(2)
            if found_title.strip() == issue["title"]:
                found[issue["title"]] = ident
                break
    return found


def main() -> int:
    # Force stdout to UTF-8 so titles with → and similar print on cp1252.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    linear = LinearClient(repo_root=REPO_ROOT)
    existing = _existing_by_title(linear)
    if existing:
        print(f"Found {len(existing)} pre-existing issue(s) by title; will skip.\n")

    key_to_id: dict[str, str] = {}
    for issue in ISSUES:
        if issue["title"] in existing:
            ident = existing[issue["title"]]
            key_to_id[issue["key"]] = ident
            print(f"  ~ {ident:7s} {issue['key']:20s} (already exists)")
            continue

        labels: list[str] = [issue["type_label"]]
        if issue.get("subsystem"):
            labels.append(issue["subsystem"])
        labels.append(issue["track"])
        labels.extend(issue.get("strategic", []))

        out = linear.create(
            title=issue["title"],
            description=issue["description"],
            priority=issue.get("priority"),
            labels=labels,
            state="Backlog",
        )
        match = _CREATED_RE.search(out)
        if not match:
            print(f"  ! create returned unexpected output for {issue['key']!r}: {out!r}")
            continue
        identifier = match.group(1)
        key_to_id[issue["key"]] = identifier
        print(f"  + {identifier:7s} {issue['key']:20s} {issue['title']}")

    print(f"\nResolved {len(key_to_id)} issues. Linking blockers...\n")

    linked = 0
    for blocker_key, blocked_key in BLOCKS:
        blocker_id = key_to_id.get(blocker_key)
        blocked_id = key_to_id.get(blocked_key)
        if not (blocker_id and blocked_id):
            print(f"  ! skipping {blocker_key} -> {blocked_key} (one missing)")
            continue
        out = linear.link(blocker_id, blocked_id)
        print(f"  link {blocker_id} blocks {blocked_id}: {out.strip()}")
        linked += 1

    print(f"\nDone. Created {len(key_to_id)} issues, linked {linked} blockers.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
