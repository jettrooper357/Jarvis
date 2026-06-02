# Change Impact Notice: Task–Code Linkage

- **Date:** 2026-06-01
- **Status:** Approved (design + plan approved in the 2026-06-01 brainstorming
  session; see `docs/superpowers/specs/2026-06-01-task-code-linkage-design.md`
  and `docs/superpowers/plans/2026-06-01-task-code-linkage.md`)
- **Approval required:** Yes — granted by the user during brainstorming.

## What is changing

Sub-project 3 of the Autonomous Workflow Engine. Additive:

- **New package** `src/openjarvis/codelink/`:
  - `context.py` — `WorkContext` (thread-safe active task/agent/project) +
    `work_context` contextmanager.
  - `store.py` — `CodeLinkStore` (append-only SQLite-WAL, two tables:
    `file_events` + `code_change_links`) and the `FileEvent` /
    `CodeChangeLink` dataclasses.
  - `watcher.py` — optional `watchdog`-based filesystem watcher.
  - `git_recorder.py` — `record_head_commit` (reuses `git_tool._run_git`).
- **New tools** (`tools/codelink_tools.py`): `codelink_set_work_context`,
  `codelink_record_file_event`, `codelink_record_commit`, `codelink_query`.
- **New `[codelink]` config section**: `enabled` (default true), `db_path`
  (default `~/.openjarvis/codelink.db`), `watch_enabled` (default **false**).
- **New read-only REST routes** under `/v1/codelink` (`file-events`, `commits`,
  `tasks/{id}`, `status`), mounted via `include_all_routes`.
- **App startup wiring** in `server/app.py` (store always when enabled; watcher
  only when `watch_enabled`).

## Why the change is needed

Link file/code changes to the work that caused them, so Jarvis can answer "why
was this file changed", "which task does this code belong to", and "who/what
changed it" — the project-automation core of the workflow engine.

## Benefits

- Durable, queryable file-change and commit history linked to tasks/agents/
  projects (soft links by id).
- Active-task `WorkContext` attributes changes without per-call boilerplate.
- Optional live watcher captures human and agent edits in project folders.

## Risks and mitigations

- **Risk:** A new optional always-on filesystem watcher **thread**.
  **Mitigation:** OFF by default (`watch_enabled = false`); behind a
  `watchdog` optional-import guard that degrades to a no-op (never raises);
  the FS-event→record mapping is isolated and independently tested.
- **Risk:** `watchdog` is in the lockfile but not always importable.
  **Mitigation:** `watchdog_available()` probe + graceful no-op manager.
- **Risk:** New SQLite file.
  **Mitigation:** auto-creates at `~/.openjarvis/codelink.db`; soft links only
  (no FK into the project DB); deletable with no cross-subsystem impact;
  opt-out via `[codelink].enabled = false`.

## Affected files / modules

Created: `src/openjarvis/codelink/{__init__,context,store,watcher,git_recorder}.py`,
`src/openjarvis/tools/codelink_tools.py`,
`src/openjarvis/server/codelink_routes.py`, plus tests under `tests/codelink/`,
`tests/tools/`, `tests/core/`, `tests/server/`.

Modified: `src/openjarvis/core/config.py` (`CodeLinkConfig` + field +
`top_sections` + `__all__`), `src/openjarvis/tools/__init__.py` (import),
`src/openjarvis/server/app.py` (wiring),
`src/openjarvis/server/api_routes.py` (mount).

## User-visible behavior changes

None unless the `/v1/codelink` API or the codelink tools are used, or
`watch_enabled` is turned on. Recording is otherwise silent and explicit.

## Migration steps

None. The store creates its SQLite database on first use. To use the live
watcher, install `watchdog` and set `[codelink].watch_enabled = true`.

## Rollback steps

1. `git revert` the commit range for this change.
2. Optionally delete `~/.openjarvis/codelink.db`.

No other subsystem depends on Task–Code Linkage, so rollback is clean.
