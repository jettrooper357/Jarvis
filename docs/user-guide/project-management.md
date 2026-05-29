# Project Management

OpenJarvis includes a local-first project management workspace: a portfolio
of projects with nested tasks/subtasks, assignment and status metadata,
notes, a timeline/Gantt view, a KPI dashboard, and AI summaries — all backed
by a single store that both the UI **and** AI agents read from.

## Quick start

```bash
# Bootstrap the feature (writes ~/.openjarvis/config.toml)
jarvis init --preset project-management

# Start the server + UI, then open the Projects page from the sidebar
jarvis serve
```

Everything persists to `~/.openjarvis/projects.db` (SQLite). There is no
browser-local silo — project data is server-side so agents can query it.

## Concepts

| Concept | Description |
|---|---|
| **Project** | Portfolio entry: name, description, owner, team, start/target dates, status (`Planning`, `Active`, `At Risk`, `Delayed`, `Complete`), progress, tags, milestones. |
| **Task** | Belongs to a project; can nest under a `parent_task_id` (subtasks). Has type, optional `category`, status (`Backlog`, `Ready`, `In Progress`, `Blocked`, `Review`, `Done`, `Cancelled`), assignee, owner, priority, dates, percent complete, dependencies. |
| **Category** | Optional project-scoped label that groups tasks/subtasks under the same name. Stored on the project so an explicitly-created category persists even before any task uses it. |
| **Milestone** | Named target (with optional date and done flag) tracked on the project. |
| **Note** | Attached to a task: `Comment`, `Decision`, `Action Item`, or `Update`, with an optional AI summary. |

Project progress automatically rolls up from the average `percent_complete`
of its top-level tasks.

## The UI

Sidebar → **Projects**:

- **Projects** — portfolio cards with status and progress; create new projects inline.
- **Project detail** (`/projects/:id`) — nested task tree on the left, a task
  detail/edit panel on the right (status, assignee, priority, dates, percent
  complete, notes). Add tasks and subtasks from the tree.
- **Timeline** (`/projects/:id/timeline`) — Gantt chart: bars span start→due,
  the lighter fill is percent complete, overdue bars turn red.
- **Dashboard** (`/projects/dashboard`) — portfolio KPIs (active/at-risk
  projects, overdue/blocked/in-progress tasks, average completion), workload
  by assignee, and at-risk signal cards.
- **AI summary** — on a project, click *AI summary* to get an LLM-generated
  health summary and next action (falls back to a deterministic summary if no
  engine is available).

## Mission Control

The sidebar **Mission Control** page (`/dashboard`, formerly "Dashboard")
augments the on-device engine telemetry with a live project + agent view:

- **Projects · tasks & subtasks** — every project with its nested task tree,
  per-task and per-project progress bars, and status. Each task shows the
  agents linked to it with a live working/idle indicator and their current
  activity.
- **Agents** — the full managed-agent roster grouped by working vs idle, each
  tagged with its role tier and the task it is on.

It refreshes on a short poll and immediately on any agent event, and is fed
by a single aggregate call (`GET /v1/projects/mission-control`).

### Agent work is always tied to a project task

Agent work is tracked under the project plan, not in a parallel silo:

- **Hard requirement.** Every managed-agent task must reference an existing
  project task or subtask (`project_task_id`). Creating an agent task — via
  the API, the `managed_agent_assign_task` tool, or starting a run — fails
  with a clear error if it is not linked.
- **Migration.** Agent tasks that pre-date this requirement are auto-linked
  on upgrade to a system **"Unassigned Work"** project (tagged
  `needs-reconciliation`) with a per-agent catch-all task, so existing
  agents keep running. Reassign them to real project tasks, then archive
  that project.
- **Auto-update.** While an agent runs, its linked project task is updated
  in place: a note is recorded on start and finish (or failure), the task is
  nudged to *In Progress*, a failed run marks it *Blocked*, and a successful
  run on a leaf task with no subtasks completes it. Progress is never
  over-claimed for tasks with subtasks.

### Role tiers

What an agent may change is governed by its org-chart role (the free-text
`org_role` plus org-chart position — an agent with no manager sits at the
top). Tiers, matched case-insensitively (function-first, so a "QA Lead" is
QA, not a manager):

| Tier | Matches | May |
|---|---|---|
| **Project Management / Manager** | `manager`, `project manage`, `pm`, `director`, `lead`, `owner`, `chief`, `head`, or top of the org chart | Full project & task CRUD, (re)assignment, scheduling |
| **Worker / Operative** (default) | everything else | Update only its own assigned task (status, %, notes); add subtasks under its task |
| **Quality Assurance / QA Testing** | `qa`, `quality`, `test`, `review` | Read all; add notes; pass/fail a task under test; file bug subtasks. No project CRUD or reassignment |

## Data source & agents

The `project_management` connector (Data Sources page) normalizes every
project — metadata + nested task tree + notes — into the knowledge pipeline.
With it connected, the bundled **Project Assistant** agent template (Agents
page) can answer questions grounded in real project data:

- "Summarize Project X status"
- "What should I work on next?"
- "What's blocked or overdue?"
- "Generate a sprint plan for the next two weeks"

The connector also reads optional extra local project folders
(`.json`/`.md`/`.yaml`) listed in its editable JSON config
(`~/.openjarvis/connectors/project_management.json`, editable from the Data
Sources page).

### Project tools (write actions)

Project-capable agents (manager/chief tier — see role tiers above) also get a
write toolset so they can maintain the plan and log progress directly,
instead of only answering from knowledge:

- `project_create`, `project_create_task` (tasks/subtasks, with optional
  `category`), `project_update_task`, `project_delete_task`
- `project_add_note` — log a progress/status note whenever the agent is
  given an update on the work
- `project_add_milestone`, `project_update_milestone`,
  `project_delete_milestone`
- `project_add_category`, `project_rename_category` (propagates to every
  task using the old name), `project_delete_category` (tasks become
  uncategorized; the tasks are kept)
- `project_import_outline` — bulk-import a whole multi-level work breakdown
  (Categories, Tasks, Subtasks) in **one** call instead of looping
  `project_create_task`

These act on the same SQLite `ProjectStore` as the UI and REST API, so
changes show up everywhere.

### Pasting a big outline into chat

You can paste a whole project breakdown into the chat and have it imported
in one shot. Two grammars are accepted:

- **Prefixed labels** — `Category: <name>`, `Task: <name>`,
  `SubTask: <name>` (case-insensitive; the common `Catgory:` typo is
  tolerated). Name the destination project in your intro line, e.g.
  *"add this to the Veridex project"*.
- **Numbered Markdown** — `N.` is a Category, `N.M` is a Task, and `*`/`-`
  bullets are Subtasks.

When the runtime sees a multi-level outline, it imports it **deterministically
server-side** — the model is not asked to echo the (potentially huge) outline
back as a tool argument, which previously overflowed the token budget and left
the chat with no reply. The Chief still delivers the import summary, and the
`project_import_outline` call shows up in the conversation/event log. If no
target project name can be found in the message, the request falls back to the
normal model turn.

### `project-status-report` skill

A built-in skill that packages the assistant's core job: it pulls the named
project's data from the `project_management` data source via knowledge
search, then produces a grounded report — a health summary,
risks/blocked/overdue items, and the prioritized next actions. Run it from
the CLI:

```bash
jarvis skill run project-status-report --arg project="My Project"
```

It's also on the Library page, and the **Project Assistant** agent can call
it directly.

## REST API

All UI actions are thin clients over these endpoints (useful for scripting):

| Method & path | Purpose |
|---|---|
| `GET/POST /v1/projects` | List / create projects |
| `GET/PUT/DELETE /v1/projects/{id}` | Read / update / delete a project |
| `GET/POST /v1/projects/{id}/tasks` | List / create tasks (subtasks via `parent_task_id`) |
| `PUT/DELETE /v1/projects/tasks/{task_id}` | Update / delete a task |
| `GET/POST /v1/projects/tasks/{task_id}/notes` | List / add notes |
| `PUT/DELETE /v1/projects/notes/{note_id}` | Update / delete a note |
| `GET /v1/projects/dashboard` | Portfolio KPIs |
| `GET /v1/projects/mission-control` | Aggregate: projects + nested tasks + linked agents + KPIs |
| `POST /v1/projects/{id}/ai-summary` | AI (or heuristic) project summary |

## Configuration

The preset (`configs/openjarvis/examples/project-management.toml`) enables a
project-oriented toolset and the data source:

```toml
[project_management]
enabled = true
sources = ["local_project_files"]

[project_management.local_project_files]
path = "~/.openjarvis/projects"

[connectors.project_management]
enabled = true
```
