#!/usr/bin/env npx tsx
/**
 * Linear CLI for personal-assistant.
 *
 * Adapted from taylor1355/npc-simulation/tools/linear-pm with team-key
 * parameterization and dependency-relation authoring (link/unlink).
 *
 * Auth: LINEAR_API_KEY (required), LINEAR_TEAM_KEY (default "PA").
 */

import { LinearClient } from "@linear/sdk";

const API_KEY = process.env.LINEAR_API_KEY;
if (!API_KEY) {
  console.error("Set LINEAR_API_KEY environment variable");
  process.exit(1);
}

const TEAM_KEY = (process.env.LINEAR_TEAM_KEY || "PA").toUpperCase();
const IDENTIFIER_RE = new RegExp(`^${TEAM_KEY}-(\\d+)$`, "i");

const client = new LinearClient({ apiKey: API_KEY });

// --- Team / state helpers ---

let _cachedTeam: any = null;
async function getTeam() {
  if (_cachedTeam) return _cachedTeam;
  const teams = await client.teams();
  const match = teams.nodes.find((t) => t.key.toUpperCase() === TEAM_KEY);
  if (match) {
    _cachedTeam = match;
    return match;
  }
  if (teams.nodes.length === 0) {
    throw new Error("No teams found in this Linear workspace.");
  }
  if (teams.nodes.length === 1) {
    _cachedTeam = teams.nodes[0];
    return teams.nodes[0];
  }
  const keys = teams.nodes.map((t) => t.key).join(", ");
  throw new Error(
    `Team with key "${TEAM_KEY}" not found. Available: ${keys}. ` +
      `Set LINEAR_TEAM_KEY in .env.`
  );
}

async function getStates(teamId: string): Promise<Record<string, string>> {
  const team = await client.team(teamId);
  const states = await team.states();
  const map: Record<string, string> = {};
  for (const s of states.nodes) map[s.name] = s.id;
  return map;
}

// issueSearch is broken in @linear/sdk v78 (double-encodes variables).
// Use team.issues() with filters instead.
async function findByIdentifier(identifier: string) {
  const id = identifier.toUpperCase();
  const match = id.match(IDENTIFIER_RE);
  if (!match) return null;
  const num = parseInt(match[1]!);
  const team = await getTeam();
  const issues = await team.issues({
    filter: { number: { eq: num } },
    first: 1,
  });
  return issues.nodes[0] || null;
}

async function searchByTitle(query: string) {
  const team = await getTeam();
  const issues = await team.issues({
    filter: { title: { containsIgnoreCase: query } },
    first: 20,
  });
  return issues.nodes;
}

const PRIORITY_NAMES: Record<string, number> = {
  none: 0,
  urgent: 1,
  high: 2,
  medium: 3,
  low: 4,
  "0": 0,
  "1": 1,
  "2": 2,
  "3": 3,
  "4": 4,
};
const PRIORITY_LABELS: Record<number, string> = {
  0: "None",
  1: "Urgent",
  2: "High",
  3: "Medium",
  4: "Low",
};
const PRIORITY_TAGS: Record<number, string> = {
  0: "---",
  1: "URG",
  2: "HI ",
  3: "MED",
  4: "LOW",
};

// --- Commands ---

async function whoami() {
  const me = await client.viewer;
  const team = await getTeam();
  const states = await team.states();
  const labels = await client.issueLabels({ first: 200 });
  console.log(`User:   ${me.name} <${me.email}>`);
  console.log(`Team:   ${team.name} (${team.key})`);
  console.log(`States: ${states.nodes.map((s) => s.name).join(", ")}`);
  const labelNames = labels.nodes.map((l) => l.name).sort();
  console.log(`Labels: ${labelNames.length > 0 ? labelNames.join(", ") : "(none yet)"}`);
}

async function status() {
  const team = await getTeam();
  const states = await team.states();
  const stateNames = ["In Progress", "Todo", "Blocked", "Backlog", "Triage"];

  for (const stateName of stateNames) {
    const state = states.nodes.find((s) => s.name === stateName);
    if (!state) continue;

    const issues = await client.issues({
      first: 50,
      filter: {
        team: { id: { eq: team.id } },
        state: { id: { eq: state.id } },
      },
    });

    const count = issues.nodes.length;
    if (count === 0 && !["In Progress", "Todo", "Blocked"].includes(stateName)) continue;

    console.log(`\n## ${stateName} (${count})`);
    for (const issue of issues.nodes.slice(0, 15)) {
      const project = await issue.project;
      const projStr = project ? ` [${project.name}]` : "";
      const tag = PRIORITY_TAGS[issue.priority] ?? "???";
      console.log(`  ${tag} ${issue.identifier}: ${issue.title}${projStr}`);
    }
    if (count > 15) console.log(`  ... and ${count - 15} more`);
  }
}

async function todo() {
  const team = await getTeam();
  const stateMap = await getStates(team.id);
  const todoStateId = stateMap["Todo"];
  if (!todoStateId) {
    console.error("Todo state not found in this team's workflow.");
    process.exit(1);
  }

  const issues = await client.issues({
    first: 50,
    filter: {
      team: { id: { eq: team.id } },
      state: { id: { eq: todoStateId } },
    },
  });

  issues.nodes.sort((a, b) => (a.priority || 5) - (b.priority || 5));

  console.log(`## Todo Issues (${issues.nodes.length})\n`);
  for (const issue of issues.nodes) {
    const labels = await issue.labels();
    const typeLabel = labels.nodes.find((l) =>
      [
        "feature",
        "bug",
        "tech-debt",
        "investigation",
        "docs",
        "life-task",
        "research",
        "vault-organization",
        "reading",
        "health",
        "relationship",
      ].includes(l.name.toLowerCase())
    );
    const project = await issue.project;
    const projStr = project ? ` [${project.name}]` : "";
    const prio = PRIORITY_LABELS[issue.priority] ?? "?";
    console.log(
      `- **${issue.identifier}** (${prio}${typeLabel ? ", " + typeLabel.name : ""}): ${issue.title}${projStr}`
    );
  }
}

async function projectInfo(projectName: string) {
  const projects = await client.projects({ first: 50 });
  const project = projects.nodes.find(
    (p) => p.name.toLowerCase() === projectName.toLowerCase()
  );
  if (!project) {
    console.error(`Project "${projectName}" not found.`);
    if (projects.nodes.length > 0) {
      console.log("Available:", projects.nodes.map((p) => p.name).join(", "));
    } else {
      console.log("(no projects in this workspace yet)");
    }
    return;
  }

  const issues = await project.issues({ first: 100 });
  const byState: Record<string, any[]> = {};
  for (const issue of issues.nodes) {
    const state = await issue.state;
    const name = state?.name || "Unknown";
    if (!byState[name]) byState[name] = [];
    byState[name]!.push(issue);
  }

  console.log(`## ${project.name}\n`);
  console.log(`${project.description || ""}\n`);

  const total = issues.nodes.length;
  const done = (byState["Done"] || []).length;
  console.log(
    `Progress: ${done}/${total} (${total > 0 ? Math.round((done / total) * 100) : 0}%)\n`
  );

  for (const [state, stateIssues] of Object.entries(byState)) {
    if (state === "Done" || state === "Cancelled" || state === "Canceled") continue;
    console.log(`### ${state} (${stateIssues.length})`);
    for (const issue of stateIssues) {
      console.log(`  ${issue.identifier}: ${issue.title}`);
    }
  }
}

async function issueInfo(identifier: string) {
  const issue = await findByIdentifier(identifier);
  if (!issue) {
    console.error(`Issue ${identifier} not found`);
    return;
  }

  const state = await issue.state;
  const labels = await issue.labels();
  const project = await issue.project;
  const relations = await issue.relations();

  console.log(`## ${issue.identifier}: ${issue.title}\n`);
  console.log(`**State**: ${state?.name || "?"}`);
  console.log(`**Priority**: ${PRIORITY_LABELS[issue.priority] ?? "?"}`);
  console.log(`**Labels**: ${labels.nodes.map((l) => l.name).join(", ") || "(none)"}`);
  if (project) console.log(`**Project**: ${project.name}`);
  console.log(`**URL**: ${issue.url}`);

  const invRelations = await issue.inverseRelations();
  if (relations.nodes.length > 0 || invRelations.nodes.length > 0) {
    console.log(`\n### Relations`);
    for (const rel of relations.nodes) {
      const related = await rel.relatedIssue;
      if (related) {
        console.log(`  ${rel.type}: ${related.identifier} — ${related.title}`);
      }
    }
    for (const rel of invRelations.nodes) {
      const blocker = await rel.issue;
      if (blocker && rel.type === "blocks") {
        console.log(`  blocked by: ${blocker.identifier} — ${blocker.title}`);
      }
    }
  }

  console.log(`\n### Description\n`);
  console.log(issue.description || "(no description)");
}

async function search(query: string) {
  const results = await searchByTitle(query);
  console.log(`## Search: "${query}" (${results.length} results)\n`);
  for (const issue of results) {
    const state = await issue.state;
    console.log(`  ${issue.identifier} [${state?.name}]: ${issue.title}`);
  }
}

async function blocked() {
  const team = await getTeam();
  const stateMap = await getStates(team.id);
  const blockedId = stateMap["Blocked"];

  const blockedStateIssues = blockedId
    ? await client.issues({
        first: 50,
        filter: {
          team: { id: { eq: team.id } },
          state: { id: { eq: blockedId } },
        },
      })
    : { nodes: [] as any[] };

  const allIssues = await team.issues({ first: 250 });
  const blockedStateIssueIds = new Set(blockedStateIssues.nodes.map((i: any) => i.id));

  const allBlocked: Array<{ issue: any; blockers: string[] }> = [];

  for (const issue of allIssues.nodes) {
    const invRels = await issue.inverseRelations();
    const blockers: string[] = [];
    for (const rel of invRels.nodes) {
      if (rel.type === "blocks") {
        const blocker = await rel.issue;
        if (blocker) blockers.push(blocker.identifier);
      }
    }
    const issueState = await issue.state;
    const stateName = issueState?.name || "";
    if (stateName === "Done" || stateName === "Cancelled" || stateName === "Canceled") continue;

    if (blockers.length > 0 || blockedStateIssueIds.has(issue.id)) {
      allBlocked.push({ issue, blockers });
    }
  }

  console.log(`## Blocked Issues (${allBlocked.length})\n`);
  for (const { issue, blockers } of allBlocked) {
    const blockerStr =
      blockers.length > 0 ? ` (blocked by: ${blockers.join(", ")})` : " (manually blocked)";
    console.log(`  ${issue.identifier}: ${issue.title}${blockerStr}`);
  }
}

async function next() {
  const team = await getTeam();
  const stateMap = await getStates(team.id);
  if (!stateMap["Todo"]) {
    console.log("No Todo state in this team's workflow.");
    return;
  }

  const todoIssues = await client.issues({
    first: 50,
    filter: {
      team: { id: { eq: team.id } },
      state: { id: { eq: stateMap["Todo"] } },
    },
  });

  if (todoIssues.nodes.length === 0) {
    console.log("No Todo issues. Check Backlog for items to promote.");
    return;
  }

  // Sort by priority client-side and skip blocked.
  todoIssues.nodes.sort((a, b) => (a.priority || 5) - (b.priority || 5));
  const candidates = [];
  for (const issue of todoIssues.nodes) {
    const invRels = await issue.inverseRelations();
    const isBlocked = invRels.nodes.some((r) => r.type === "blocks");
    if (!isBlocked) candidates.push(issue);
  }

  console.log("## Suggested Next Issues\n");
  console.log("Top candidates from Todo, ordered by priority, blockers excluded:\n");

  for (const issue of candidates.slice(0, 5)) {
    const labels = await issue.labels();
    const project = await issue.project;
    const labelStr = labels.nodes.map((l) => l.name).join(", ");
    const projStr = project ? ` [${project.name}]` : "";
    const prio = PRIORITY_LABELS[issue.priority] ?? "?";
    console.log(`**${issue.identifier}** (${prio}): ${issue.title}${projStr}`);
    if (labelStr) console.log(`  Labels: ${labelStr}`);
    console.log(`  URL: ${issue.url}\n`);
  }
}

async function setState(args: string[]) {
  const stateWords: string[] = [];
  const identifiers: string[] = [];
  for (const arg of args) {
    if (IDENTIFIER_RE.test(arg)) {
      identifiers.push(arg);
    } else if (identifiers.length === 0) {
      stateWords.push(arg);
    } else {
      console.error(
        `Unexpected argument "${arg}" after issue IDs. Usage: set-state <State Name> <id> [id...]`
      );
      process.exit(1);
    }
  }

  const stateName = stateWords.join(" ");
  if (!stateName || identifiers.length === 0) {
    console.error(`Usage: set-state <State Name> <${TEAM_KEY}-XX> [${TEAM_KEY}-YY ...]`);
    process.exit(1);
  }

  const team = await getTeam();
  const stateMap = await getStates(team.id);
  const stateId = stateMap[stateName];
  if (!stateId) {
    console.error(
      `State "${stateName}" not found. Available: ${Object.keys(stateMap).join(", ")}`
    );
    process.exit(1);
  }

  let failed = false;
  for (const id of identifiers) {
    const issue = await findByIdentifier(id);
    if (!issue) {
      console.error(`Issue ${id} not found`);
      failed = true;
      continue;
    }
    await client.updateIssue(issue.id, { stateId });
    console.log(`${issue.identifier} → ${stateName}`);
  }
  if (failed) process.exit(1);
}

async function setPriority(args: string[]) {
  if (args.length < 2) {
    console.error(
      `Usage: set-priority <priority> <${TEAM_KEY}-XX> [${TEAM_KEY}-YY ...]`
    );
    console.error("Priority: 0=None, 1=Urgent, 2=High, 3=Medium, 4=Low");
    process.exit(1);
  }

  const priority = PRIORITY_NAMES[args[0]!.toLowerCase()];
  if (priority === undefined) {
    console.error(
      `Unknown priority "${args[0]}". Use: None, Urgent, High, Medium, Low (or 0-4)`
    );
    process.exit(1);
  }

  const identifiers = args.slice(1);
  let failed = false;
  for (const id of identifiers) {
    const issue = await findByIdentifier(id);
    if (!issue) {
      console.error(`Issue ${id} not found`);
      failed = true;
      continue;
    }
    await client.updateIssue(issue.id, { priority });
    console.log(`${issue.identifier} priority → ${PRIORITY_LABELS[priority]}`);
  }
  if (failed) process.exit(1);
}

async function createIssue(args: string[]) {
  let data: {
    title: string;
    description?: string;
    priority?: number;
    labels?: string[];
    state?: string;
  };

  if (args.length > 0 && !args[0]!.startsWith("--")) {
    const title = args[0]!;
    const flags: Record<string, string[]> = {};
    let i = 1;
    while (i < args.length) {
      if (args[i]!.startsWith("--")) {
        const key = args[i]!.slice(2);
        const values: string[] = [];
        i++;
        while (i < args.length && !args[i]!.startsWith("--")) {
          values.push(args[i]!);
          i++;
        }
        flags[key] = (flags[key] || []).concat(values);
      } else {
        i++;
      }
    }

    const priorityArg = (flags.priority || [])[0]?.toLowerCase();
    data = {
      title,
      description: (flags.description || []).join(" ") || undefined,
      priority: priorityArg ? PRIORITY_NAMES[priorityArg] : undefined,
      labels: flags.label || undefined,
      state: (flags.state || [])[0] || undefined,
    };
  } else {
    let input = "";
    for await (const chunk of process.stdin) input += chunk;
    data = JSON.parse(input);
  }

  if (!data.title) {
    console.error('Usage: create "Title" [--priority P] [--label L ...] [--description "D"] [--state S]');
    console.error("Or pipe JSON: echo '{\"title\":\"...\"}' | linear create");
    process.exit(1);
  }

  const team = await getTeam();
  const stateMap = await getStates(team.id);

  const allLabels = await client.issueLabels({ first: 200 });
  const labelMap: Record<string, string> = {};
  for (const l of allLabels.nodes) labelMap[l.name.toLowerCase()] = l.id;

  const labelIds = (data.labels || [])
    .map((name: string) => labelMap[name.toLowerCase()])
    .filter(Boolean) as string[];

  const result = await client.createIssue({
    teamId: team.id,
    title: data.title,
    description: data.description || "",
    priority: data.priority || 0,
    labelIds,
    stateId: stateMap[data.state || "Triage"] || stateMap["Backlog"],
  });

  const issue = await result.issue;
  if (issue) {
    console.log(`Created ${issue.identifier}: ${issue.title}`);
    console.log(`URL: ${issue.url}`);
  }
}

async function updateIssue() {
  let input = "";
  for await (const chunk of process.stdin) input += chunk;

  const data = JSON.parse(input);
  if (!data.identifier) {
    console.error(`JSON must include 'identifier' (e.g., ${TEAM_KEY}-1)`);
    process.exit(1);
  }

  const issue = await findByIdentifier(data.identifier);
  if (!issue) {
    console.error(`Issue ${data.identifier} not found`);
    process.exit(1);
  }

  const updatePayload: Record<string, any> = {};

  if (data.title) updatePayload.title = data.title;
  if (data.description !== undefined) updatePayload.description = data.description;

  if (data.priority !== undefined) {
    const p =
      typeof data.priority === "string"
        ? PRIORITY_NAMES[data.priority.toLowerCase()]
        : data.priority;
    if (p !== undefined) updatePayload.priority = p;
  }

  if (data.state) {
    const team = await getTeam();
    const stateMap = await getStates(team.id);
    const stateId = stateMap[data.state];
    if (stateId) updatePayload.stateId = stateId;
    else console.warn(`State "${data.state}" not found, skipping state update`);
  }

  if (data.labels) {
    const allLabels = await client.issueLabels({ first: 200 });
    const labelMap: Record<string, string> = {};
    for (const l of allLabels.nodes) labelMap[l.name.toLowerCase()] = l.id;

    const labelIds = (data.labels as string[])
      .map((name: string) => labelMap[name.toLowerCase()])
      .filter(Boolean);

    if (labelIds.length > 0) updatePayload.labelIds = labelIds;
  }

  if (Object.keys(updatePayload).length === 0) {
    console.log("No fields to update");
    return;
  }

  await client.updateIssue(issue.id, updatePayload);
  console.log(`Updated ${issue.identifier}: ${data.title || issue.title}`);
  console.log(`URL: ${issue.url}`);
}

async function comment(args: string[]) {
  if (args.length < 2) {
    console.error(`Usage: comment <${TEAM_KEY}-XX> <body...>  (use - to read body from stdin)`);
    process.exit(1);
  }
  const identifier = args[0]!;
  let body = args.slice(1).join(" ");
  if (body === "-") {
    let input = "";
    for await (const chunk of process.stdin) input += chunk;
    body = input.replace(/\s+$/, "");
  }
  if (!body) {
    console.error("Empty comment body");
    process.exit(1);
  }

  const issue = await findByIdentifier(identifier);
  if (!issue) {
    console.error(`Issue ${identifier} not found`);
    process.exit(1);
  }

  const result = await client.createComment({ issueId: issue.id, body });
  if (result.success) {
    console.log(`Comment added to ${issue.identifier}`);
  } else {
    console.error("Failed to add comment");
    process.exit(1);
  }
}

async function link(args: string[]) {
  if (args.length < 2) {
    console.error(
      `Usage: link <blocker-id> <blocked-id>\n` +
        `  e.g. link ${TEAM_KEY}-5 ${TEAM_KEY}-12  (means: ${TEAM_KEY}-5 blocks ${TEAM_KEY}-12)`
    );
    process.exit(1);
  }
  const blocker = await findByIdentifier(args[0]!);
  const blocked = await findByIdentifier(args[1]!);
  if (!blocker) {
    console.error(`Issue ${args[0]} not found`);
    process.exit(1);
  }
  if (!blocked) {
    console.error(`Issue ${args[1]} not found`);
    process.exit(1);
  }

  const result = await client.createIssueRelation({
    issueId: blocker.id,
    relatedIssueId: blocked.id,
    type: "blocks",
  });
  if (result.success) {
    console.log(`${blocker.identifier} now blocks ${blocked.identifier}`);
  } else {
    console.error("Failed to create relation");
    process.exit(1);
  }
}

async function unlink(args: string[]) {
  if (args.length < 2) {
    console.error(`Usage: unlink <blocker-id> <blocked-id>`);
    process.exit(1);
  }
  const blocker = await findByIdentifier(args[0]!);
  const blocked = await findByIdentifier(args[1]!);
  if (!blocker || !blocked) {
    console.error(`Issue not found: ${!blocker ? args[0] : args[1]}`);
    process.exit(1);
  }

  const relations = await blocker.relations();
  let relationId: string | null = null;
  for (const rel of relations.nodes) {
    if (rel.type !== "blocks") continue;
    const related = await rel.relatedIssue;
    if (related && related.id === blocked.id) {
      relationId = rel.id;
      break;
    }
  }

  if (!relationId) {
    console.error(`No 'blocks' relation found from ${blocker.identifier} to ${blocked.identifier}`);
    process.exit(1);
  }

  const result = await client.deleteIssueRelation(relationId);
  if (result.success) {
    console.log(`Unlinked: ${blocker.identifier} no longer blocks ${blocked.identifier}`);
  } else {
    console.error("Failed to delete relation");
    process.exit(1);
  }
}

// --- Main ---

const [, , command, ...args] = process.argv;

async function main() {
  switch (command) {
    case "whoami":
      await whoami();
      break;
    case "status":
      await status();
      break;
    case "todo":
      await todo();
      break;
    case "project":
      await projectInfo(args.join(" "));
      break;
    case "issue":
      await issueInfo(args[0]!);
      break;
    case "pickup":
      await setState(["In Progress", ...args]);
      break;
    case "done":
      await setState(["Done", ...args]);
      break;
    case "search":
      await search(args.join(" "));
      break;
    case "blocked":
      await blocked();
      break;
    case "next":
      await next();
      break;
    case "create":
      await createIssue(args);
      break;
    case "update":
      await updateIssue();
      break;
    case "set-state":
      await setState(args);
      break;
    case "set-priority":
      await setPriority(args);
      break;
    case "comment":
      await comment(args);
      break;
    case "link":
      await link(args);
      break;
    case "unlink":
      await unlink(args);
      break;
    default:
      console.log(
        `Usage: linear <command> [args]\n` +
          `\n` +
          `Read:    whoami | status | todo | project <name> | issue <id> |\n` +
          `         search <query> | blocked | next\n` +
          `Write:   pickup <id> [id...] | done <id> [id...] |\n` +
          `         set-state <State Name> <id> [id...] |\n` +
          `         set-priority <priority> <id> [id...] |\n` +
          `         create "Title" [--priority P] [--label L ...] [--description D] [--state S] |\n` +
          `         update  (json on stdin: {identifier, title?, description?, priority?, state?, labels?}) |\n` +
          `         comment <id> <body|->  (- reads from stdin) |\n` +
          `         link <blocker> <blocked> | unlink <blocker> <blocked>`
      );
  }
}

main().catch((err) => {
  console.error(`Error: ${err.message || err}`);
  process.exit(1);
});
