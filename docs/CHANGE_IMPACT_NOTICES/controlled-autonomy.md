# Change Impact Notice: Controlled Autonomy (Rollback + Audit)

- **Date:** 2026-06-02
- **Status:** Approved (design + plan approved in the 2026-06-02 brainstorming
  session; see
  `docs/superpowers/specs/2026-06-02-controlled-autonomy-design.md` and
  `docs/superpowers/plans/2026-06-02-controlled-autonomy.md`)
- **Approval required:** Yes — granted by the user during brainstorming.

## What is changing

The backend capstone of the Autonomous Workflow Engine. Additive:

- **New package** `src/openjarvis/autonomy/`:
  - `handlers.py` — an undo-handler registry + a built-in `file_write` handler.
  - `rollback_store.py` — `RollbackStore` (append-only SQLite-WAL, two tables)
    + `ReversibleAction` + `RollbackError`. Records reversible actions and
    reverts them via the handler registry.
  - `audit.py` — `build_audit_report` over the Persisted Event Log.
- **New tools** (`tools/autonomy_tools.py`): `rollback_record`,
  `rollback_list`, `rollback_revert`, `audit_report`.
- **New `[autonomy]` config section**: `enabled` (default true), `db_path`
  (default `~/.openjarvis/autonomy.db`).
- **New REST routes** `GET/POST /v1/rollback`, `GET /v1/rollback/{id}`,
  `POST /v1/rollback/{id}/revert`, `GET /v1/audit/report` (mounted via
  `include_all_routes`).
- **App startup wiring** in `server/app.py` (construct the rollback store).

## Why the change is needed

Most of "controlled autonomy" already existed (the `AgentScheduler` does
cron/interval/IFTTT autonomous scheduling; approval-gating pauses risky tool
calls; the Event Log is the audit substrate). The two genuine gaps were
**rollback history** (record + undo reversible autonomous actions) and
**audit reports** (compile what happened over a window). This slice fills them.

## Benefits

- Reversible autonomous actions can be recorded and one-click reverted (where
  safely undoable), with a full audit trail.
- An Event-Log audit report answers "what happened, to which task/agent, when".

## Risks and safety posture

- **Rollback only undoes recorded reversible actions** via their registered
  undo handler on the stored `undo_payload`. It performs **no new outward
  action**.
- **Inherently irreversible types** (`email`, `deploy`, `http_post`) have no
  handler — they are recorded for audit and **never auto-undone**; a revert
  request returns a "compensating action required" status, not an undo.
- **Handler failure** is captured: the action is marked `failed` (with the
  error) and the failure is surfaced; the DB reflects the real state.
- Opt-out via `[autonomy].enabled = false`; wiring is wrapped so it never
  blocks startup.

## Does NOT change

The `AgentScheduler`, `TaskScheduler`, and approval-gating execution paths are
untouched. No existing tool auto-records reversible actions yet (wiring
`file_write` etc. to auto-record is a deferred follow-up).

## Affected files / modules

Created: `src/openjarvis/autonomy/{__init__,handlers,rollback_store,audit}.py`,
`src/openjarvis/tools/autonomy_tools.py`,
`src/openjarvis/server/autonomy_routes.py`, plus tests under `tests/autonomy/`,
`tests/tools/`, `tests/core/`, `tests/server/`.

Modified: `src/openjarvis/core/config.py` (`AutonomyConfig` + field +
`top_sections` + `__all__`), `src/openjarvis/tools/__init__.py` (import),
`src/openjarvis/server/app.py` (wiring),
`src/openjarvis/server/api_routes.py` (mount).

## User-visible behavior changes

None unless the `/v1/rollback*` / `/v1/audit/report` API or the `rollback_*` /
`audit_report` tools are used.

## Migration steps

None. The store creates its SQLite database on first use.

## Rollback steps

1. `git revert` the commit range for this change.
2. Optionally delete `~/.openjarvis/autonomy.db`.

No other subsystem depends on it, so rollback is clean.
