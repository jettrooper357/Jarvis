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
| **Task** | Belongs to a project; can nest under a `parent_task_id` (subtasks). Has type, status (`Backlog`, `Ready`, `In Progress`, `Blocked`, `Review`, `Done`, `Cancelled`), assignee, owner, priority, dates, percent complete, dependencies. |
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
