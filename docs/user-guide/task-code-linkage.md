# Task–Code Linkage

Task–Code Linkage records file changes and commits and links them to the work
that caused them, so Jarvis can answer:

- **Why was this file changed?** — list the file's recorded events.
- **Which task does this code belong to?** — events/commits carry a `task_id`.
- **Who/what changed it?** — events carry an `agent_id` and a `source`.

## Records

- **FileEvent** — a single file change: `path`, `change_type`
  (`created`/`modified`/`deleted`/`moved`), `project_id`, `task_id`,
  `agent_id`, `source` (`watcher`/`tool`/`git`), `at`, `old_path` (for moves),
  `size`.
- **CodeChangeLink** — a commit linked to a task: `commit_sha`, `repo_path`,
  `project_id`, `task_id`, `agent_id`, `message`, `files_changed`,
  `insertions`, `deletions`, `committed_at`, `recorded_at`.

Both live in an append-only SQLite store at `~/.openjarvis/codelink.db`.

## Active work context

A process-global `WorkContext` holds the task/agent/project currently being
worked. When a record is created **without** an explicit `task_id` (etc.), the
blank fields are stamped from the context. Explicit arguments always override
it. Set it with the `codelink_set_work_context` tool, or scope it in code with
the `work_context(...)` contextmanager.

## Agent tools

- `codelink_set_work_context` — set the active task/agent/project.
- `codelink_record_file_event` — record a file change explicitly.
- `codelink_record_commit` — record a repo's current HEAD commit, linked to a
  task (reads sha, message, and numstat via git).
- `codelink_query` — look up changes/commits by `task_id` or `path`.

## File watcher (optional)

A live filesystem watcher can auto-record changes in each project's
`working_folder`. It requires the optional `watchdog` package and is **off by
default**. Enable it in `~/.openjarvis/config.toml`:

```toml
[codelink]
enabled = true          # default true
watch_enabled = true    # default false — turn on the live watcher
```

If `watchdog` is not installed or `watch_enabled` is false, the watcher is a
no-op (the store and tools still work). The watcher ignores `.git`,
`__pycache__`, `node_modules`, `.venv`, `build`, `dist`, and `.pyc/.pyo/.swp/~`
files.

## REST API

All endpoints are under `/v1/codelink` and read-only; they return empty results
when the store is disabled (never an error).

| Method & path | Purpose |
|---|---|
| `GET /v1/codelink/file-events` | Filter by `path`, `project_id`, `task_id`, `limit` |
| `GET /v1/codelink/commits` | Filter by `commit_sha`, `task_id`, `project_id`, `limit` |
| `GET /v1/codelink/tasks/{task_id}` | Combined file-events + commits for a task ("why was this changed") |
| `GET /v1/codelink/status` | `watchdog_available`, `store_configured`, `active_watchers` |

## Out of scope (current)

EventBus emission of `file.changed`/`code.change.linked`, storing diff/content
snapshots (fetch on demand via the git tool), commit-message/branch parsing for
linkage, and any UI are deferred to later slices.
