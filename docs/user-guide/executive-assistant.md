# Executive Assistant

Jarvis's Chief Orchestrator doubles as your Executive Assistant (EA). It
coordinates four capabilities under a single ingress: the daily briefing,
inbox triage, a **Follow-Up Tracker**, and a **Decision Log**. Briefing and
triage reuse the existing `morning_digest` and `inbox_triager`; the follow-up
and decision features are new.

In v1 the EA works through **chat** (ask the Chief) and **scheduled delivery**
(the existing briefing path). There is no dedicated UI yet.

## Enabling EA mode

EA capabilities on the Chief are gated by a feature flag (default off). Enable
it in `~/.openjarvis/config.toml`:

```toml
[assistant]
enabled = true
```

This surfaces as `assistant_mode` when the Chief prompt is built. With the flag
off, the Chief behaves exactly as before.

## Follow-Up Tracker

Track things you are waiting on, or owe a reply to, and get nudged when they
go stale.

| Tool | Purpose | Key parameters |
|---|---|---|
| `followup_add` | Create a follow-up | `summary`, `counterparty` (required); `direction` (`waiting_on`\|`owe_reply`), `source_ref`, `linked_task_id`, `linked_project_id`, `sla_due_at` |
| `followup_list` | List follow-ups | `status`, `counterparty`, `stale_only` |
| `followup_resolve` | Close one | `followup_id` (required); `status` (`resolved`\|`cancelled`) |
| `followup_sweep_stale` | Mark open + past-SLA items as `nudged` | `now` (optional epoch override) |

Run `followup_sweep_stale` on a schedule (e.g. via the scheduler) to surface
stale items in your briefing.

## Decision Log

Record decisions and approvals durably, with who approved them and when, linked
to a project or task.

| Tool | Purpose | Key parameters |
|---|---|---|
| `decision_record` | Record a decision/approval | `statement` (required); `rationale`, `decided_by`, `approved_by`, `source_ref`, `linked_task_id`, `linked_project_id`, `supersedes` |
| `decision_list` | List decisions | `linked_project_id`, `linked_task_id`, `status` (`active`\|`superseded`\|`revoked`) |

Decisions are immutable; recording a decision with `supersedes` set marks the
prior decision `superseded`. Record only user-safe rationale — never hidden
reasoning.

## Subordinate agents

- **Decision Recorder** (`decision_recorder` template) — captures decisions
  from conversation and writes them via `decision_record`.
- **Priority Advisor** (`priority_advisor` template) — reviews calendar, open
  project work, and stale follow-ups to recommend what matters today.

Both return their results upward to the Chief; they never reply to the user
directly.

## Data location

The stores create SQLite databases under `~/.openjarvis/`: `followups.db` and
`decisions.db`.
