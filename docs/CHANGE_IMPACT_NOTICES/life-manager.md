# Change Impact Notice: Life Manager

- **Date:** 2026-06-01
- **Status:** Approved (design + plan approved in the 2026-06-01 brainstorming
  session; see `docs/superpowers/specs/2026-06-01-life-manager-design.md` and
  `docs/superpowers/plans/2026-06-01-life-manager.md`)
- **Approval required:** Yes — granted by the user during brainstorming.

## What is changing

Sub-project 4 of the Autonomous Workflow Engine. Additive:

- **New package** `src/openjarvis/lifemanager/`:
  - `store.py` — `LifeStore` (SQLite-WAL, two tables: `life_domains` +
    `routines`) and the `LifeDomain` / `Routine` dataclasses + `LifeError`.
    Completion-time cadence math (`next_due_at = completion_time + interval`),
    streaks, and a "what's due" query.
- **New tools** (`tools/lifemanager_tools.py`): `life_add_domain`,
  `life_add_routine`, `life_complete_routine`, `life_due`, `life_list`.
- **New `[lifemanager]` config section**: `enabled` (default true), `db_path`
  (default `~/.openjarvis/lifemanager.db`).
- **New read/write REST routes** under `/v1/life` (`domains`, `routines`,
  `routines/{id}/complete`, `due`), mounted via `include_all_routes`.
- **App startup wiring** in `server/app.py` (construct the store; mirrors the
  prior subsystem wiring).

## Why the change is needed

The existing Life Manager / health / finance / learning agent templates track
life areas by shoehorning into `project_create`/tasks + memory. This slice
gives them a real domain/routine backend with due-tracking and streaks.

## Benefits

- Durable, queryable life domains and recurring routines.
- "What's due today" via the `due` query; streak tracking on completion.
- Foundation the existing life agents (and a future Life Dashboard UI) build on.

## Risks and mitigations

- **Risk:** New SQLite file + always-constructed store.
  **Mitigation:** Opt-out via `[lifemanager].enabled = false`; wiring is wrapped
  in try/except so it never blocks startup; the DB auto-creates and is
  deletable with no cross-subsystem impact.

## Existing templates unchanged

This does **NOT** modify the `life_manager`, `health_routine`,
`finance_reminder`, `learning_coach`, or `sermon_study` agent templates.
Updating them to use the new `life_*` tools (instead of project tasks) is a
deferred follow-up.

## Affected files / modules

Created: `src/openjarvis/lifemanager/{__init__,store}.py`,
`src/openjarvis/tools/lifemanager_tools.py`,
`src/openjarvis/server/lifemanager_routes.py`, plus tests under
`tests/lifemanager/`, `tests/tools/`, `tests/core/`, `tests/server/`.

Modified: `src/openjarvis/core/config.py` (`LifeManagerConfig` + field +
`top_sections` + `__all__`), `src/openjarvis/tools/__init__.py` (import),
`src/openjarvis/server/app.py` (wiring),
`src/openjarvis/server/api_routes.py` (mount).

## User-visible behavior changes

None unless the `/v1/life` API or the `life_*` tools are used. No existing
endpoint, agent, or template behavior changes.

## Migration steps

None. The store creates its SQLite database on first use.

## Rollback steps

1. `git revert` the commit range for this change.
2. Optionally delete `~/.openjarvis/lifemanager.db`.

No other subsystem depends on the Life Manager store, so rollback is clean.
