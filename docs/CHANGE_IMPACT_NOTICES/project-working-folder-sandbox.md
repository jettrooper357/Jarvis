# Project working folder + per-project sandbox

## What is changing

1. Projects gain a `working_folder` field (filesystem path) on the
   schema, store, REST API, project tools, and the project edit dialog.
   The path is auto-created on save.
2. A new `openjarvis.projects.workspace` module exposes the active
   project's `working_folder` to the rest of the runtime via a
   `ContextVar` (`use_workspace`, `active_workspace_root`,
   `is_within_workspace`, `resolve_within_workspace`).
3. `ManagedAgentRuntime.run` looks up the agent's linked project task,
   resolves the parent project's `working_folder`, and wraps the run in
   `use_workspace(folder)`. While active:
   - `file_read`, `file_write`, `apply_patch` reject paths outside the
     workspace; relative paths resolve against it.
   - `shell_exec` defaults `cwd` to the workspace and rejects any
     caller-supplied `working_dir` outside it.
4. The project edit dialog now binds Start date / End date to real
   draft state (was hard-coded `defaultValue="2025-04-22"` /
   `"2025-05-23"` strings) and persists them via the API. A new
   "Working folder" field appears for project rows.

## Why

The user asked for projects to carry a working folder so agents can
"go there and work on tasks for each project." The JARVIS Foundation
Guide treats filesystem access as a policy-controlled capability and
requires dangerous actions to be scope-limited and auditable; a
per-project sandbox root is the simplest enforcement boundary.

The hard-coded dates in the edit dialog were also the immediate
source of the "tasks are dated last year" report — uncontrolled inputs
showed `2025-04-22` regardless of the actual stored value.

## Benefits

- Agents working on different projects can't trample each other's
  files. A subagent that misbehaves is bounded by the project root.
- Operators can move project work onto fast disk by changing one
  field; existing projects keep working with no folder set.
- The Mission Control edit dialog now shows and saves real dates.

## Risks

- An agent doing work on Project A and Project B back-to-back gets
  two different sandbox roots. If a tool kept a relative path between
  runs, it now resolves under a different root. Mitigation: tools take
  fully resolved paths; the contextvar is per-run.
- A misconfigured working folder (typo, missing drive) will block
  filesystem tool calls for that project. The error surfaces in tool
  output, not silently.
- The sandbox is enforced inside the Python tool wrappers. A
  subprocess started by `shell_exec` can still wander after launch.
  This is the same trust model as before for shell commands; the
  workspace gates the entry point, not subprocess descendants.
- Existing projects get `working_folder = ''` (unset). With nothing
  set, behavior is unchanged — no sandboxing kicks in. Operators must
  opt in per project.

## Affected files

- `src/openjarvis/projects/store.py` — schema column, migration,
  `_normalize_working_folder` helper, create/update plumbing.
- `src/openjarvis/projects/workspace.py` — new module.
- `src/openjarvis/projects/__init__.py` — re-exports.
- `src/openjarvis/tools/project_tools.py` — `working_folder` param on
  `project_create`, new `project_update` tool, `_format_project`
  surfaces the field.
- `src/openjarvis/tools/file_read.py`,
  `src/openjarvis/tools/file_write.py`,
  `src/openjarvis/tools/apply_patch.py`,
  `src/openjarvis/tools/shell_exec.py` — workspace enforcement.
- `src/openjarvis/server/managed_agent_runtime.py` — `run()` activates
  the workspace; new `_active_project_workspace` helper.
- `frontend/src/lib/projects-api.ts` — `working_folder` in Project type.
- `frontend/src/pages/ProjectsPage.tsx` — GanttItem fields, modal
  bindings, save flow, hard-coded date defaults removed.

## User-visible behavior changes

- Project edit dialog has a "Working folder" input (project rows
  only) and the date fields now reflect/save real values.
- When a project has a working folder and an agent is assigned to one
  of its tasks, that agent's file/shell tool calls are scoped to the
  folder.

## Migration

- Schema migration is in-place via `_ADDED_COLUMNS`; existing DBs gain
  the `working_folder` column with default `''`.
- No tool retraining needed; `working_folder = ''` preserves old
  behavior.

## Rollback

- Revert the listed files. The added column is harmless to leave in
  place; SQLite ignores it once the code no longer references it.

## Approval

Approved interactively by the user, who selected: full sandbox root,
project-only scope, auto-create on save.
