# Jarvis Watchtower Implementation Plan

Status: planning artifact created before implementation, 2026-06-03.

Inputs:
- `AGENTS.md`
- `docs/AUGMENTED_FEATURES.md`
- `docs/FEATURE_PRESERVATION_MATRIX.md`
- current projects, agent manager, approvals, event bus, scheduler, channel,
  and frontend route architecture.

This plan is additive-first. It does not authorize breaking changes. If any
step requires changing an existing API shape, persistence meaning, scheduler
behavior, approval behavior, channel behavior, agent workflow, or protected UI
surface, create `docs/CHANGE_IMPACT_NOTICES/<slug>.md` and stop for approval.

## 1. Existing Surfaces To Reuse

| Area | Existing implementation | Watchtower use |
| --- | --- | --- |
| Projects/tasks | `src/openjarvis/projects/store.py`, `src/openjarvis/server/projects_router.py` | Read project/task state for overdue, blocked, due-soon, stale, and risk findings. |
| Mission Control | `GET /v1/projects/mission-control`, `frontend/src/components/MissionControl/` | Frontend can reuse project/agent summaries and link findings to Command Center. |
| Agent ledger/messages | `src/openjarvis/agents/manager.py` | Read agent tasks, jobs, messages, Chief designation, and channel bindings. Append Watchtower-triggered messages through existing message APIs/helpers. |
| Chief ingress | `GET /v1/chief`, `POST /v1/chief/messages` | Normal internal routing goes to Chief first; Watchtower does not become a user-facing final answer path. |
| Approvals | `src/openjarvis/agents/approvals.py`, `/v1/approvals` | Detect stale pending approvals and link user notifications to the existing approval flow. No auto-approval. |
| Agent jobs/scheduler | `agent_jobs`, `agent_job_runs`, `AgentScheduler` | Detect failed/stale job runs without replacing scheduler execution. |
| Events | `src/openjarvis/core/events.py` | Subscribe to existing task, approval, job, agent, security, and UI notification events where available. |
| Event log/audit | `src/openjarvis/eventlog/store.py` and Watchtower store | Record Watchtower decisions, local/fallback decisions, notification attempts, and internal routes. |
| Telegram | `src/openjarvis/channels/telegram.py`, `frontend/src/lib/connectors-api.ts` | Reuse existing Telegram adapter/config; no separate Telegram system. |
| Frontend shell | `frontend/src/pages/workspaces.tsx`, `DashboardPage`, `SettingsPage` | Add Watchtower visibility to Command Center and System settings without removing existing tabs/pages. |
| Agent sidebar | `InterAgentActivityPanel` in `AgentsPage.tsx` | Label Watchtower-triggered messages in the existing activity feed. |

## 2. New Subsystem

Add:

```text
src/openjarvis/watchtower/
  __init__.py
  service.py
  rules.py
  local_reasoner.py
  priority.py
  dnd.py
  notifier.py
  internal_router.py
  store.py
  types.py
```

No existing subsystem is replaced.

## 3. Data Model

Add a new SQLite-backed `WatchtowerStore`, preferably colocated by default at
`~/.openjarvis/watchtower.db` unless config specifies otherwise.

Tables:
- `watchtower_findings`
- `watchtower_notifications`
- `watchtower_internal_routes`
- `watchtower_escalations`
- `watchtower_settings`

All tables are additive and owned by Watchtower. They do not mutate existing
project, agent, approval, scheduler, channel, or trace schemas.

Initial statuses:
- Finding: `active`, `snoozed`, `resolved`, `suppressed`
- Internal route: `pending`, `sent`, `responded`, `resolved`, `escalated`, `failed`
- Notification decision: `sent`, `deferred`, `suppressed`, `failed`

## 4. Local-AI-Only Guard

Implement in `local_reasoner.py`:

- `is_local_provider(provider_config) -> bool`
- `LocalReasoner.reason(...)`

Provider guard rejects known cloud or paid providers:
- OpenAI
- Anthropic/Claude
- Gemini/Google cloud
- OpenRouter
- any provider URL or key pattern that indicates cloud inference

Allowed local indicators:
- `ollama`
- `llamacpp`
- `llama.cpp`
- `mlx`
- `vllm` when configured with localhost/local bind only
- `sglang` when configured with localhost/local bind only
- local engine objects explicitly marked local by config/engine key

If local AI is unavailable or rejected:
- use deterministic rules
- persist/audit a `rules_fallback` decision
- never call a paid/cloud LLM

## 5. Detection Rules

Implement deterministic scans first in `rules.py`:

- overdue project tasks
- due-soon project tasks
- blocked project tasks
- stale/no-progress tasks based on `updated_at`
- project at risk from dashboard/Mission Control status
- stale/running agents with old heartbeat
- agents in `error`, `stalled`, `needs_attention`, `input_required`
- pending approvals beyond threshold
- agent job runs with `failed` status
- security/system events with emergency severity when available

All findings have stable dedupe keys:

```text
finding_type + entity_type + entity_id + priority_band
```

## 6. Priority and Routing

Implement `PriorityEngine`:

1. Deterministic priority classification is always available.
2. Local AI can only refine summary/recommended action when allowed.
3. Priority increases can bypass normal dedupe cooldown and create escalation.

Canonical priorities:
- `info`
- `low`
- `normal`
- `high`
- `urgent`
- `emergency`

Default routing:
- `info`, `low`: digest/defer
- `normal`: route to Chief; in-app only if configured
- `high`: route to Chief; notify user only for configured high user routes or approval/input blockers
- `urgent`: route to Chief and notify user subject to urgent DND setting
- `emergency`: route to Chief and notify user, DND bypass if enabled

## 7. DND Policy

Implement `DoNotDisturbPolicy`:

- Applies only to user notifications.
- Does not suppress internal routes or agent work.
- Defers low/normal by default during quiet hours.
- Emergency can bypass when configured.
- Urgent bypass follows `allow_urgent_bypass`.

## 8. Notification Routing

Implement `WatchtowerNotifier`:

- In-app notifications are emitted via `EventType.UI_NOTIFICATION` and persisted
  in `watchtower_notifications`.
- Telegram uses existing `TelegramChannel` and existing UI-managed credentials.
- Notification bodies are sanitized before sending externally.
- Telegram route respects configured min priority and DND.

No raw secrets, API keys, tokens, credentials, private code snippets, or raw
file contents are sent through Telegram.

## 9. Internal Routing

Implement `InternalRouter`:

- Default route for operational findings is Chief first.
- Use `AgentManager.get_chief_agent()`.
- Persist a row in `watchtower_internal_routes`.
- Create a Watchtower-triggered message in the Chief's message log using
  `AgentManager.send_message(...)` with structured JSON metadata where current
  schema permits, or a user-safe operational message in content.
- Do not directly execute destructive tools.
- Do not bypass approval gates.

Initial route types:
- `send_to_chief`
- `request_sub_agent_status`
- `route_to_responsible_agent`
- `escalate_to_user`
- `suppress`
- `digest_later`

Full Chief-subagent conversation orchestration can layer on the existing
managed-agent message/queue flow after route records exist.

## 10. Service Loop

Implement `WatchtowerService`:

- Optional background thread.
- Subscribe to existing event bus types:
  `TASK_CREATED`, `TASK_UPDATED`, `TASK_COMPLETED`, `TASK_FAILED`,
  `APPROVAL_REQUESTED`, `APPROVAL_RESOLVED`, `JOB_FAILED`,
  `AGENT_STALL_DETECTED`, `AGENT_TICK_ERROR`, `SECURITY_ALERT`,
  `SECURITY_BLOCK`, `UI_NOTIFICATION`.
- Periodic scan defaults to 60 seconds.
- `scan_once()` supports API-triggered manual scan.
- Store last scan time and local AI status.

Startup wiring:
- Add `app.state.watchtower_store`.
- Add `app.state.watchtower_service`.
- Start only when `watchtower.enabled` is true.
- Stop cleanly on FastAPI shutdown.

## 11. API Routes

Add `src/openjarvis/server/watchtower_routes.py` with:

- `GET /v1/watchtower/status`
- `GET /v1/watchtower/findings`
- `GET /v1/watchtower/findings/{id}`
- `POST /v1/watchtower/findings/{id}/snooze`
- `POST /v1/watchtower/findings/{id}/resolve`
- `POST /v1/watchtower/findings/{id}/escalate`
- `GET /v1/watchtower/internal-routes`
- `GET /v1/watchtower/internal-routes/{id}`
- `POST /v1/watchtower/internal-routes/{id}/resolve`
- `POST /v1/watchtower/internal-routes/{id}/escalate`
- `GET /v1/watchtower/settings`
- `PATCH /v1/watchtower/settings`
- `POST /v1/watchtower/scan-now`
- `POST /v1/watchtower/test-notification`
- `POST /v1/watchtower/route-to-chief`

Settings patch validates priorities, routes, DND values, and cooldowns.

## 12. Frontend

Add API helpers to `frontend/src/lib/api.ts`.

Command Center:
- Add Watchtower panel under the Command Center / Mission Control area.
- Tabs: `All`, `User Alerts`, `Internal Routes`, `Waiting on Agents`,
  `Waiting on Me`, `Escalated`, `Deferred`.
- Show priority badges, route badges, DND status, local AI status, Telegram
  status, last scan time, and filters.

System:
- Add `System > Watchtower` settings section inside existing settings page or
  system workspace composition.
- Do not remove current settings/logs/setup pages.

Global indicator:
- Add a compact status badge to existing app chrome/SystemPulse path if it can
  be done additively.

Agents:
- Extend activity-feed rendering to label Watchtower-triggered messages when
  existing message metadata/content identifies them.

## 13. Tests

Backend:
- Store migration and CRUD tests.
- Rule tests for overdue, blocked, stale approval, project risk, job failure.
- DND tests for deferral, emergency bypass, urgent bypass setting.
- Priority/dedupe tests including priority increase escalation.
- LocalReasoner cloud rejection and deterministic fallback tests.
- Internal route tests proving normal overdue routes to Chief, not directly to user.
- Notification routing tests proving Telegram threshold behavior.
- API route tests for status, findings, route-to-chief, settings, scan-now.

Frontend:
- Watchtower panel render tests.
- Internal route tab render tests.
- DND indicator and local AI fallback warning tests.
- Snooze/resolve/escalate API-call tests.
- Settings save test.

Regression:
- Existing scheduler tests remain unchanged.
- Existing Telegram/channel tests remain unchanged.
- Existing approval tests remain unchanged.
- Existing agent task ledger tests remain unchanged.
- Existing Chief ingress tests remain unchanged.
- Existing project/task linkage tests remain unchanged.

## 14. Rollout

Phase A:
- types, store, rules, priority, DND, local provider guard, and unit tests.

Phase B:
- notifier and internal router with persisted decisions, Chief-first routing,
  and tests.

Phase C:
- service loop and API routes.

Phase D:
- Command Center panel and System settings.

Phase E:
- broader event subscriptions, Telegram hardening, digest support, and
  sidebar labels.

## 15. Non-Goals For Initial Additive Pass

- No changes to existing approval enforcement.
- No scheduler replacement.
- No direct destructive action execution by Watchtower.
- No cloud LLM calls.
- No direct subordinate final response to the user.
- No Telegram system replacement.
- No changes to existing project/task API shapes.
