# Approval Center

The Approval Center is Jarvis's generalized queue for "do you want me to
actually do this?" decisions. When an agent proposes a potentially risky
action — a code change, a file deletion, an outbound email, a project-plan
shift, a deployment — it records an **action approval** that a human resolves
before the action proceeds. It is the safety gate for autonomous behavior.

## Relationship to tool-gating approvals

This is **distinct** from the tool-gating approval system
(`/v1/approvals`, `[approval_gating]`), which scopes a single tool invocation
to granted/denied. The Approval Center handles *arbitrary action types* with a
richer lifecycle, in its own store and under its own `/v1/action-approvals`
prefix. The two are independent.

## Lifecycle

An approval moves through these states:

- `pending` — awaiting a decision (the initial state).
- `approved` / `rejected` — **terminal and immutable**.
- `deferred` — snoozed (optional `remind_at`); re-openable.
- `needs_info` — a follow-up question was asked; re-openable once answered.
- `modified` — a revised payload was proposed (bumps `revision`); re-openable.

`reopen` returns a `deferred` / `needs_info` / `modified` approval to
`pending`. Every transition is recorded in an append-only trail.

## Configuration

In `~/.openjarvis/config.toml`:

```toml
[action_approvals]
enabled = true                              # default true; false to opt out
db_path = "~/.openjarvis/action_approvals.db"
```

## REST API

All endpoints are under `/v1/action-approvals`. Read endpoints return an empty
list when the store is disabled; write endpoints return 503.

| Method & path | Purpose |
|---|---|
| `GET /v1/action-approvals` | List, filtered by `action_type`, `state`, `agent_id`, `project_id`, `limit` |
| `POST /v1/action-approvals` | Create an approval (`action_type`, `summary`, `payload`, optional `agent_id`/`task_id`/`project_id`/`requested_by`) |
| `GET /v1/action-approvals/{id}` | Get one approval (404 if missing) |
| `GET /v1/action-approvals/{id}/history` | The append-only transition trail |
| `POST /v1/action-approvals/{id}/resolve` | Resolve via `action` ∈ `approve`/`reject`/`defer`/`ask`/`modify`/`reopen` |

### Resolve body

```json
{
  "action": "approve|reject|defer|ask|modify|reopen",
  "resolved_by": "user",
  "reason": "optional note",
  "remind_at": 1733000000.0,        // defer only (optional)
  "followup_question": "...",       // ask only (required)
  "new_payload": { "...": "..." }   // modify only (required)
}
```

Resolving an already-terminal (`approved`/`rejected`) approval returns **409**.
An unknown `action` value returns **422**.

## Data location

The store creates `~/.openjarvis/action_approvals.db` on first use.

## Out of scope (current)

The Approval Inbox UI, severity/risk levels, EventBus emission, expiry/auto-
action, and actually *executing* an approved action are deferred to later
slices. This subsystem stores and serves decisions; it does not run them.
