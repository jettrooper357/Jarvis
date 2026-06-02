# Change Impact Notice: Approval Center

- **Date:** 2026-06-01
- **Status:** Approved (design + plan approved in the 2026-06-01 brainstorming
  session; see
  `docs/superpowers/specs/2026-06-01-approval-center-design.md` and
  `docs/superpowers/plans/2026-06-01-approval-center.md`)
- **Approval required:** Yes — granted by the user during brainstorming.

## What is changing

Sub-project 2 of the Autonomous Workflow Engine. Additive:

- **New package** `src/openjarvis/approvals_center/` with `ActionApprovalStore`
  and the `ActionApproval` / `ActionApprovalError` types. Append-only
  SQLite-WAL store (two tables: `action_approvals` current state +
  `action_approval_events` transition trail) for arbitrary action types
  (code/file/email/plan/deploy) with an Approve/Reject/Modify/Defer/Ask/Reopen
  lifecycle.
- **New `[action_approvals]` config section** in `core/config.py`: `enabled`
  (default true), `db_path` (default `~/.openjarvis/action_approvals.db`).
- **New read/write REST routes** in `server/action_approvals_routes.py` under
  `/v1/action-approvals` (list, create, get, history, resolve), mounted via
  `include_all_routes`.
- **App startup wiring** in `server/app.py` (construct the store; mirrors the
  event-log wiring).

## Why the change is needed

Jarvis needs a dedicated queue to ask "do you want me to actually do this?"
for arbitrary, potentially risky actions — the safety gate that keeps
autonomous behavior governed. The existing tool-gating approvals only cover
single tool invocations with granted/denied outcomes.

## Benefits

- A single durable queue for arbitrary action approvals with a rich lifecycle.
- Append-only transition trail for auditability.
- Correlation IDs (agent/task/project) for joining to the event log and
  project store.
- Foundation for the Approval Inbox UI and Controlled-Autonomy slices.

## Distinct from tool-gating approvals

This does **NOT** touch the existing tool-gating approval system:
`src/openjarvis/agents/approvals.py` (`ApprovalStore`), the `/v1/approvals`
router, or the `[approval_gating]` config are unchanged. The new system uses a
separate package, separate tables, a separate config section, and a separate
`/v1/action-approvals` prefix. There is **no migration** and no overlap; the
two coexist.

## Risks and mitigations

- **Risk:** New always-constructed store + new SQLite file.
  **Mitigation:** Opt-out via `[action_approvals].enabled = false`; wiring is
  wrapped in try/except so it never blocks startup; the DB auto-creates and is
  deletable with no cross-subsystem impact.

## Affected files / modules

Created: `src/openjarvis/approvals_center/__init__.py`,
`src/openjarvis/approvals_center/store.py`,
`src/openjarvis/server/action_approvals_routes.py`, plus tests under
`tests/approvals_center/`, `tests/server/`, and
`tests/core/test_action_approvals_config.py`.

Modified: `src/openjarvis/core/config.py` (`ActionApprovalsConfig` + field +
`top_sections` + `__all__`), `src/openjarvis/server/app.py` (wiring),
`src/openjarvis/server/api_routes.py` (mount).

## User-visible behavior changes

None unless the `/v1/action-approvals` API is called. No existing endpoint or
behavior changes.

## Migration steps

None. The store creates its SQLite database on first use.

## Rollback steps

1. `git revert` the commit range for this change.
2. Optionally delete `~/.openjarvis/action_approvals.db`.

No other subsystem depends on the Approval Center, so rollback is clean.
