# Change Impact Notice: Persisted Event Log

- **Date:** 2026-06-01
- **Status:** Approved (design + plan approved in the 2026-06-01 brainstorming
  session; see
  `docs/superpowers/specs/2026-06-01-persisted-event-log-design.md` and
  `docs/superpowers/plans/2026-06-01-persisted-event-log.md`)
- **Approval required:** Yes — granted by the user during brainstorming.

## What is changing

Sub-project 1 of the Autonomous Workflow Engine. Additive:

- **New package** `src/openjarvis/eventlog/` with `EventLogStore` and the
  `EventRecord` dataclass. Append-only SQLite-WAL store that subscribes to the
  in-memory `EventBus` and persists every event (minus a config denylist).
- **Indexed correlation columns** extracted from each event payload:
  `agent_id`, `task_id`, `project_id`, `run_id`; the full payload is preserved
  as JSON.
- **New `[eventlog]` config section** in `core/config.py`: `enabled`
  (default true), `db_path` (default `~/.openjarvis/eventlog.db`), `denylist`
  (default empty).
- **New read-only REST routes** in `server/eventlog_routes.py`:
  `GET /v1/events` (filtered) and `GET /v1/events/feed` (activity feed),
  mounted via `include_all_routes`.
- **App startup wiring** in `server/app.py`: constructs the store and
  subscribes it to the bus (mirrors the existing trace-store wiring).

## Why the change is needed

The `EventBus` is in-memory only; history is lost on restart. AGENTS.md
mandates append-only event storage for auditability and "the UI may derive
logs from events, but it must not be the canonical store." A durable,
queryable event log provides traceability and is the foundation for the
Approval Center, Task–Code Linkage, audit reports, and the activity feed.

## Benefits

- Durable, queryable history of everything that flows through the bus.
- Answers "what happened to task/agent/project X, and when" via indexed IDs.
- Foundation other workflow-engine sub-projects build on.

## Risks and mitigations

- **Risk:** A new subscriber on (almost) every `EventType` adds write load.
  **Mitigation:** `[eventlog].denylist` drops high-volume noise; writes are
  small and synchronous to a WAL DB; the whole subsystem is opt-out via
  `[eventlog].enabled = false`.
- **Risk:** A failing persist could disrupt event publishing.
  **Mitigation:** `record()` swallows and logs any exception — capture never
  crashes the publishing thread or an agent turn.
- **Risk:** New SQLite file on disk.
  **Mitigation:** Auto-creates at `~/.openjarvis/eventlog.db`; deletable with
  no impact on other subsystems.

## Affected files / modules

Created: `src/openjarvis/eventlog/__init__.py`,
`src/openjarvis/eventlog/store.py`,
`src/openjarvis/server/eventlog_routes.py`, plus tests under
`tests/eventlog/` and `tests/server/`, and `tests/core/test_eventlog_config.py`.

Modified: `src/openjarvis/core/config.py` (`EventLogConfig` + field +
`top_sections` + `__all__`), `src/openjarvis/server/app.py` (wiring),
`src/openjarvis/server/api_routes.py` (mount).

## User-visible behavior changes

None unless the `/v1/events` API is called. Event capture is silent and
background; no existing endpoint or behavior changes.

## Migration steps

None. The store creates its SQLite database on first use.

## Rollback steps

1. `git revert` the commit range for this change.
2. Optionally delete `~/.openjarvis/eventlog.db`.

No other subsystem depends on the event log, so rollback is clean.
