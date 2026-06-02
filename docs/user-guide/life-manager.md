# Life Manager

The Life Manager gives Jarvis a durable backend for organizing personal life
across **domains** (work, church, health, home, …) and **routines** (recurring
habits within a domain), with due-tracking and streaks. It's what lets the
Life Manager and health/finance/learning agents answer "what's due today?" and
track consistency over time.

## Domains and routines

- **LifeDomain** — a life area: `name`, `slug` (e.g. `health`/`church`/`home`),
  `description`.
- **Routine** — a recurring habit in a domain: `title`, `cadence`
  (`daily`/`weekly`/`monthly`/`custom`), `interval_days` (used for `custom`),
  `status` (`active`/`paused`/`archived`), `next_due_at`, `last_done_at`,
  `streak`.

Both live in an SQLite store at `~/.openjarvis/lifemanager.db`.

## Cadence and due semantics

Completing a routine advances it from the **completion time**:
`next_due_at = completed_at + interval`, where the interval is daily = 1 day,
weekly = 7 days, monthly = 30 days, or custom = `interval_days` days. Each
completion also bumps the `streak` by one and records `last_done_at`.

The **due** query returns active routines whose `next_due_at` is null (never
completed) or in the past — "what's owed today". Paused and archived routines
are excluded.

## Configuration

In `~/.openjarvis/config.toml`:

```toml
[lifemanager]
enabled = true                              # default true; false to opt out
db_path = "~/.openjarvis/lifemanager.db"
```

## Agent tools

- `life_add_domain` — create a life domain (name, slug, description).
- `life_add_routine` — create a routine (title, domain_id, cadence,
  interval_days).
- `life_complete_routine` — mark a routine done (advances next-due, bumps
  streak).
- `life_due` — list routines due now.
- `life_list` — list domains, or routines filtered by domain/status.

## REST API

All endpoints are under `/v1/life`. Reads return empty lists when the store is
disabled; writes return 503.

| Method & path | Purpose |
|---|---|
| `GET /v1/life/domains` | List domains |
| `POST /v1/life/domains` | Create a domain (`name` required) |
| `GET /v1/life/routines` | List routines (filters: `domain_id`, `status`, `limit`) |
| `POST /v1/life/routines` | Create a routine (`title` required) |
| `POST /v1/life/routines/{id}/complete` | Complete a routine (advances due, bumps streak) |
| `GET /v1/life/due` | Routines due now (param `now`, `limit`) |

Creating a routine with an invalid cadence returns **422**; completing a
missing routine returns **409**.

## Out of scope (current)

A per-completion adherence/occurrence log, updating the existing life agent
templates to use the `life_*` tools, a Life Dashboard UI, and overdue
reminders/notifications are deferred to later slices. The `due` query is the
building block for reminders.
