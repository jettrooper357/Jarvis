# Event Log

The Event Log is durable, queryable history behind Jarvis's in-memory
`EventBus`. The bus remains the live source of truth for runtime dispatch; the
event log persists every event to SQLite so the system can answer "what
happened, to which task/agent/project, and when" — and so future automation,
audit, and the activity feed have a record to read from.

## How it works

At server startup (when enabled), an `EventLogStore` subscribes to the
`EventBus` for every event type except those you deny, and writes each event to
an append-only SQLite table. Event capture is isolated: a persistence failure
is logged and dropped, never crashing the publishing thread or an agent turn.

Each row stores the event type, timestamp, the full JSON payload, and four
**indexed correlation columns** extracted from the payload: `agent_id`,
`task_id`, `project_id`, `run_id`. These make per-task / per-agent / per-project
queries fast.

## Configuration

In `~/.openjarvis/config.toml`:

```toml
[eventlog]
enabled = true                       # default true; set false to opt out
db_path = "~/.openjarvis/eventlog.db"  # default location
denylist = []                         # EventType values to NOT persist
```

### Denylist guidance

The `EventBus` carries some very high-volume event types. If the log grows too
fast or you only care about meaningful workflow events, deny the noisy ones by
their `EventType` *value* (the dotted string):

```toml
[eventlog]
denylist = ["inference_start", "inference_end", "telemetry_record"]
```

Denied types are simply never subscribed, so they cost nothing.

## REST API

Both endpoints are read-only and return `{"events": [...]}` newest-first. If
the store is disabled they return an empty list (never an error).

### `GET /v1/events`

Filtered query. All parameters are optional:

| Param | Meaning |
|---|---|
| `event_type` | e.g. `task.created` |
| `agent_id` | events for one agent |
| `task_id` | events for one task |
| `project_id` | events for one project |
| `run_id` | events for one run/correlation id |
| `since` / `until` | epoch-seconds time window |
| `limit` | max rows (default 100) |

### `GET /v1/events/feed`

Newest-first activity feed across all event types. Parameters: `limit`
(default 50), `since`.

Each event is returned with its `id`, `event_type`, raw `timestamp`, an ISO
`created_at`, the four correlation IDs, and the full `data` payload.
