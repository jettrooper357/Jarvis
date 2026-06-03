# Controlled Autonomy (Rollback + Audit)

Jarvis can act on its own — the `AgentScheduler` runs agents on cron/interval/
IFTTT triggers, and approval-gating pauses risky tool calls for human sign-off.
This page covers the two pieces that make that autonomy *accountable*:
**rollback** (undo a recorded reversible action) and **audit reports**
(what happened over a window).

## Rollback model

When an agent performs a potentially risky, reversible action, it records a
**reversible action** with an `undo_payload`. Later, `revert` undoes it by
dispatching to a registered **undo handler**:

- **`file_write`** (built in) — payload `{path, prior_content}`: restores the
  prior bytes, or deletes the file if it was newly created (`prior_content` is
  null).
- **Irreversible types** (`email`, `deploy`, `http_post`, …) have **no
  handler**. They are recorded for audit but **never auto-undone** — a revert
  request returns a "compensating action required" status.
- **Handler failure** marks the action `failed` (capturing the error) and
  surfaces it; the action is never left in a hybrid state.

Add your own handlers with `register_undo_handler(action_type, fn)` from
`openjarvis.autonomy.handlers`.

### Action lifecycle

```
record → active        (reversible + handler exists)
       → irreversible  (no handler, or reversible=False)
active → reverted      (revert succeeded)
       → failed        (handler raised; error captured)
```

## Audit reports

`build_audit_report` (and the `audit_report` tool / `GET /v1/audit/report`)
compiles activity from the Persisted Event Log over a time window, with
optional `agent_id` / `task_id` / `project_id` filters — the spine of "what ran
and when". It degrades gracefully (empty report + a note) when the event log
isn't configured.

## Configuration

In `~/.openjarvis/config.toml`:

```toml
[autonomy]
enabled = true                          # default true; false to opt out
db_path = "~/.openjarvis/autonomy.db"
```

## Agent tools

- `rollback_record` — record a reversible action (action_type, summary,
  undo_payload, reversible).
- `rollback_list` — list recorded actions (filter by status/agent_id/action_type).
- `rollback_revert` — revert an action by id (undoes it if reversible).
- `audit_report` — compile the Event Log audit report for a window.

## REST API

| Method & path | Purpose |
|---|---|
| `GET /v1/rollback` | List reversible actions (filters: status, agent_id, action_type, limit) |
| `POST /v1/rollback` | Record a reversible action |
| `GET /v1/rollback/{id}` | Get one action (404 if missing) |
| `POST /v1/rollback/{id}/revert` | Revert an action (409 if already reverted) |
| `GET /v1/audit/report` | Event-Log audit report (since, until, agent_id, task_id, project_id, limit) |

Rollback writes return 503 when the store is disabled; reads degrade to empty.

## What this does not change

The scheduler and approval-gating execution paths are untouched. No existing
tool auto-records reversible actions yet — wiring tools like `file_write` to
auto-record is a deferred follow-up; for now actions are recorded explicitly
via the tool/API.
