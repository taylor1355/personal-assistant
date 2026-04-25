# Vault Organization

Spec for the agent's vault-organization work — frontmatter schemas per folder type, Bases views the agent maintains, and the migration discipline. Distinct from issue tracking (Linear's job).

## Why this is first-class

The user's vault has rich folder structure but minimal frontmatter or tags — organization is filename- and folder-driven. This is a stated weakness, not a convention to preserve. Adding structured properties unlocks Obsidian Bases (native since 1.9), which gives the user organizational dashboards over their own content with no plugin dependency.

The `vault_organizer` subagent treats this as ongoing work. It proposes frontmatter additions incrementally, never in a sweep — the user reviews each batch, the agent learns the user's preferred schema as it goes.

## Discipline

- **All vault-org changes go through the proposal queue.** Even adding a single frontmatter field is a `vault_edit` proposal; no silent migration.
- **One folder type at a time.** A vault-org wake picks one folder family and works only within it (e.g., "today: add `status`/`due` frontmatter to `02 - Todos/` files"). Mixing families confuses review.
- **Schema before content.** Before adding properties to existing notes, the agent proposes the schema in `00 - Assistant/Schemas/<folder>.yaml` for user approval. Once approved, subsequent proposals reference the schema by version.
- **Migrate readers along with writers.** When adding a new property, the agent also creates the matching Bases view that consumes it. A property nobody queries earns nothing.
- **Honor what's already there.** Literature notes already carry Zotero-driven frontmatter; the schema for that folder mirrors what's present, doesn't replace it.

## Frontmatter schemas

Defaults the agent proposes. The user sees these as schema proposals first; they're not locked in.

### `02 - Todos/*.md`

```yaml
---
status: open           # open | done | dropped
category: Health       # Free-form: Jenny / Wedding / Health / Family & Friends / Organization / Finance / Work
priority: medium       # low | medium | high (Linear-aligned)
due: 2026-05-01        # ISO date, optional
created: 2026-04-25
related: [[Project-Name]]   # optional wiki-link to related project note
---
```

The agent's todo-completion detection (v0) writes `status: done` rather than strikethrough once this schema is adopted; the strikethrough fallback stays as a transitional path.

### `04 - Plans/Dated/*.md`

```yaml
---
date: 2026-06-13       # primary scheduling key
status: planned        # planned | confirmed | done | cancelled
type: trip             # trip | appointment | milestone | reminder
related: [[...]]       # optional
---
```

### `03 - Personal Projects/<project>/*.md`

Project root note (`<project>/<project>.md` or similar):
```yaml
---
status: active         # active | paused | archived
started: 2026-01-15
linear_team: PA        # if tracked in Linear
linear_project: vault-cleanup    # Linear project slug
---
```

Per-project sub-notes (design docs, brainstorms, etc.) are case-by-case; the agent doesn't impose a generic schema here.

### `98 - Literature Notes/`

Already managed by Zotero integration (citekey, status, dateread, tags). The agent observes and surfaces but does not propose changes here unless the user asks.

### `01 - Journals/`

Year-collated; the agent does NOT add frontmatter to these. Their structure (heading-per-day) is what makes them work.

### `05 - Records/`

Reference material. Schema TBD per sub-folder; agent proposes when activity warrants.

## Bases views

The agent creates and maintains Bases views (`.base` files) under `00 - Assistant/Views/`. Each view consumes one or more frontmatter schemas. View creation is itself a proposal.

### v1 starter views

| View | Source | Filter | Sort |
|---|---|---|---|
| `Active Todos` | `02 - Todos/` | `status: open` | priority desc, due asc |
| `Done This Week` | `02 - Todos/` | `status: done` AND modified within 7 days | modified desc |
| `Upcoming Plans` | `04 - Plans/Dated/` | `date >= today AND date < today + 30d` | date asc |
| `Active Projects` | `03 - Personal Projects/` | `status: active` | started desc |
| `Stale Notes` | full vault, frontmatter-bearing | modified >60d AND `status != archived` | modified asc |
| `Reading: In Progress` | `98 - Literature Notes/` | `status: in-progress` | dateread desc |

Each view ships with a one-paragraph "what to do with this" header in the same `.base` file so the user can pick up its purpose at a glance.

### Discovery loop

A scheduled `vault_organizer` wake (weekly) audits:
- Folders with frontmatter where no Bases view consumes it → propose a view.
- Bases views that haven't been opened in N days → propose archive or removal.
- Notes that are missing properties their folder's schema requires → propose backfill.

## MOCs (Maps of Content)

`00 - Assistant/MOCs/<topic>.md` — agent-maintained index notes. One MOC per topic the agent observes is dense (>15 related notes, frequent cross-linking). MOC content:
- Wiki-link list of relevant notes, organized by sub-topic
- One-line description per link
- Periodically rebuilt from frontmatter + link analysis

MOCs differ from Bases views: views are dynamic queries; MOCs are curated narratives. Both have their place.

## Restructuring

Folder-level changes (moving files, renaming folders, splitting a folder into sub-folders) require the user-approved proposal queue and are emitted **one at a time** with the new path explicitly listed. Bulk restructures are forbidden — the user must be able to evaluate each move.

## What this is NOT

- Not a Linear mirror. Issue lists, status, priorities live in Linear; the vault has knowledge and working notes.
- Not a tag system imposed top-down. The agent proposes; the user defines the taxonomy through approval/rejection.
- Not a one-time migration. The expectation is years of incremental refinement as content evolves.

## Inbox-driven shortcuts

When the user dumps text into the inbox like "organize my probability theory notes" or "all my workout entries should have a `volume` property," the `intake_agent` routes to `vault_organizer` directly. The user can reach into vault organization without thinking about which subagent to invoke.
