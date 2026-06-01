# Feature Preservation Matrix

> **Status:** Phase 1 audit artifact, generated 2026-05-20.
> **Companion to:** `docs/ARCHITECTURE_DRIFT_REPORT.md`,
> `docs/AUGMENTED_FEATURES.md`.
> **Purpose:** for every protected feature, predict its **maximum possible
> blast radius** under the kind of Phase 2 work the user has scoped
> (Hermes/OpenClaw-style chain-of-command refactor), rate the risk, and
> name the tests that must already exist (or be added) to detect a
> regression.
>
> **Important:** this matrix is *forecast*, not authorization. No change
> below is approved. Any non-additive change still requires a Change Impact
> Notice under `docs/CHANGE_IMPACT_NOTICES/<slug>.md`.
>
> **Update 2026-05-22 — Phases 2A–2D and 2E shipped.** The additive
> phases (foundational schema, Capability Inspector, task events,
> approval data plane) and Phase 2E (Chief-as-canonical-ingress, approved
> via `docs/CHANGE_IMPACT_NOTICES/chief-as-canonical-ingress.md`, flag now
> live) all landed. The surfaces they added — `POST /v1/chief/messages`
> and siblings, the `is_chief` flag, `task.*` events, the approval store,
> config version history — are now themselves **protected** features;
> see `docs/AUGMENTED_FEATURES.md`. The rows below remain the canonical
> blast-radius forecast for any *further* work.

---

## How to read

- **Feature** — protected feature from `AUGMENTED_FEATURES.md`.
- **Implementation area** — canonical file(s).
- **Proposed Phase 2 impact** — the strongest plausible interaction with
  the planned Chief-as-ingress / task-ledger / capability-policy work.
  "Additive only" means the Phase 2 plan can extend without altering this
  contract. "Adapter required" means a compatibility shim is needed.
  "Breaking — needs Notice" means a Change Impact Notice must precede any
  edit.
- **Risk level** — Low / Medium / High based on how visible breakage would
  be and how many other features depend on this one.
- **Test coverage needed** — the tests that must guard the regression.
  "✅ exists" if a test already lives in `tests/`; "➕ to add" if Phase 2
  must produce it.
- **Migration needed?** — does the change require a data migration
  (SQLite ALTER TABLE, back-fill, etc.)?

---

## 1. Ingress & Chief routing

| Feature | Implementation area | Proposed Phase 2 impact | Risk | Test coverage needed | Migration needed? |
|---|---|---|---|---|---|
| `POST /v1/chat/completions` (OpenAI-compatible chat) | `src/openjarvis/server/routes.py`, `frontend/src/lib/sse.ts:18` | **Additive only** — keep endpoint, behavior unchanged. Frontend `ChatPage` routes through a new Chief endpoint in parallel. Old endpoint stays for third-party OpenAI-compatible clients. | High (third-party API surface) | ➕ contract test: `/v1/chat/completions` response shape unchanged with and without `agent_id` | No |
| `POST /v1/managed-agents/{agentId}/messages` (`sendAgentMessage`) | `frontend/src/lib/api.ts:1136-1148`, `server/agent_manager_routes.py` | **Adapter required** — keep the route; default frontend ingress moves to Chief; this route stays for power-user "talk directly to subordinate" use behind a clear UI affordance. | High | ✅ `tests/server/test_agent_manager_routes.py` (extend); ➕ test confirming InteractTab can still reach a subordinate directly | No |
| Chief action envelope (`OrchestratorAction`) | `src/openjarvis/agents/chief.py:1-34` | **Additive only** — Phase 2 introduces a Chief ingress that *consumes* this envelope; no shape change. | Low | ✅ Phase 2 must add unit tests for each action type round-trip | No |
| OrchestratorAgent "chief" mode | `src/openjarvis/agents/orchestrator.py:97` | **Additive only** — Phase 2 builds on the mode flag. | Low | ✅ existing orchestrator tests; ➕ chief-mode delegation path | No |
| `ChiefPendingCard` (mid-turn input requests) | `frontend/src/pages/AgentsPage.tsx:2293` | **Additive only** — Phase 2 may extend its event source to include approval requests. | Low | ➕ UI test that an `awaiting_input` task surfaces in the card | No |

## 2. Task ledger & status vocabulary

| Feature | Implementation area | Proposed Phase 2 impact | Risk | Test coverage needed | Migration needed? |
|---|---|---|---|---|---|
| `agent_tasks` table | `src/openjarvis/agents/manager.py:32-42` | **Additive (ALTER TABLE)** — add nullable `parent_task_id`, `root_task_id`, `request_source`, `requesting_user`, `priority`, `updated_at`, `completed_at`, `summary`, `errors_json`, `requires_user_input`, `requires_approval`. Existing rows continue to read. | Medium | ✅ `tests/server/test_agent_manager_routes.py`; ➕ migration test that old rows are readable post-ALTER | **Yes** — additive |
| Task status enum (`pending` / `active` / `completed` / `failed`) | `agents/manager.py`, surfaced in `frontend/src/lib/api.ts:492` | **Adapter required** — introduce canonical statuses in `core/types.py`; map old↔new at read/write boundary; UI consumes canonical; old strings keep working. | Medium | ➕ unit tests for the mapping in both directions; ➕ regression test that old task rows still render in the UI Tasks tab | Light (re-mapping at boundary; data already valid) |
| Agent status enum (`idle` / `running` / `paused` / `error` / `archived` / `needs_attention` / `budget_exceeded` / `stalled` / `input_required` / `auth_required` / `waiting_on_tool`) | `frontend/src/lib/api.ts:465` | **No change planned** — agent status vocab is already richer than task vocab and aligns with operational needs. | Low | ✅ existing tests; ➕ snapshot test of `StatusBadge` rendering for each | No |
| Project ↔ agent-task linkage (`project_task_id`, `project_id`) | `agents/manager.py` (post-migration columns) | **Additive only** — new task fields layer below this; cardinality unchanged. | Low | ✅ `tests/server/test_mission_control.py`; ➕ test that new `parent_task_id` and existing `project_task_id` coexist | No |
| Default "Unassigned Work" routing for chat-created tasks | `src/openjarvis/server/managed_agent_runtime.py` | **No change planned** | Low | ✅ existing managed-agent runtime tests | No |
| `managed_agent_delegate`, `managed_agent_assign_task`, `managed_agent_directory` tools | `src/openjarvis/tools/managed_agent_tools.py` | **Adapter required** — `managed_agent_assign_task` may switch from `start_now=True` (block-and-run) to `start_now=True` (enqueue) under a feature flag, with the synchronous path preserved for tests/legacy. | Medium | ✅ `tests/tools/`; ➕ tests that enqueue + execute produces same final result as synchronous run | No (behavioral, not schema) |
| Chief-pending question/answer flow | server side + `AgentsPage.tsx:2293` | **Additive only** — extended to approval requests, not removed. | Low | ➕ test that an approval request renders alongside a free-text question | No |

## 3. Capability system

| Feature | Implementation area | Proposed Phase 2 impact | Risk | Test coverage needed | Migration needed? |
|---|---|---|---|---|---|
| `effective_agent_tool_names` auto-injection (collab / project / knowledge) | `src/openjarvis/agents/capabilities.py:105-125` | **Additive** — extend with `inherited_tool_names`, `blocked_tool_names`, `requires_approval_tool_names`; existing return shape preserved (or extended with new keys). | Medium | ✅ existing capability tests; ➕ tests for inheritance, blocks, approval-required | No |
| `enrich_agent_record` API shape (`configured_*`, `effective_*`, `auto_tools`, `knowledge_enabled`) | `capabilities.py:128-142`, consumed by frontend `ManagedAgent` type (`frontend/src/lib/api.ts:451-485`) | **Additive only** — new keys are added; existing keys keep their meaning. | Medium (frontend reads it) | ➕ JSON-schema-style contract test on the agent record returned by `/v1/managed-agents` | No |
| `build_agent_tool_instances(restrict_to_tool_names=...)` | `capabilities.py:212-346` | **No change planned** — least-privilege primitive stays; Phase 2 will *use* it more (e.g. honor block lists). | Low | ✅ existing tests; ➕ test that block list short-circuits dispatch | No |
| Templates (`.toml` + library loader) | `src/openjarvis/agents/library.py`, `agents/templates/*.toml` | **No change planned** | Low | ✅ existing tests | No |
| Skill registry + tool adapter | `src/openjarvis/skills/`, `skills/tool_adapter.py` | **No change planned** | Low | ✅ existing tests | No |
| `AgentPresetToolsSection` editor UI | `frontend/src/pages/AgentsPage.tsx:2565` | **Additive only** — add badges for `assigned / inherited / effective / disabled / protected / approval-required`; do not remove existing chip semantics. | Medium | ➕ snapshot tests for each badge state | No |

## 4. Observability surfaces

| Feature | Implementation area | Proposed Phase 2 impact | Risk | Test coverage needed | Migration needed? |
|---|---|---|---|---|---|
| `/v1/agents/events` WebSocket | server runtime + `frontend/src/lib/useAgentEvents.ts:10-111` | **Additive only** — new event types (`task.*`, `approval.*`) are added to the same stream; existing event consumers keep working. | High (frontend live UX depends on it) | ➕ contract test fixing the WebSocket frame shape; ➕ replay test that a sequence of `task.*` events drives the `InterAgentActivityPanel` to the expected DOM | No |
| `InterAgentActivityPanel` sidebar | `frontend/src/pages/AgentsPage.tsx:3814` | **Additive only** — add visual treatments for task lifecycle and approval requests; existing filters (`all`/`active`/`alerts`/`direct`) preserved. | High (canonical operational log) | ➕ render test per filter mode | No |
| `AgentOrgChart` with live pulse | `frontend/src/pages/AgentsPage.tsx:3594` | **No change planned** | Low | ✅ ad-hoc; ➕ test that pulse activates on `agent.turn.started` | No |
| SSE stream bridge `/v1/chat/completions` event vocabulary | `src/openjarvis/server/stream_bridge.py:1-368` | **No change planned** | High (third-party) | ✅ existing routes tests; ➕ contract snapshot of the event names | No |
| Trace store schema (`traces`, `trace_steps`, `parent_trace_id`, `run_id`, FTS) | `src/openjarvis/traces/store.py:81-250` | **Additive only** — task IDs may be added as a `metadata` key; schema not touched. | Low | ✅ `tests/traces/test_store_fts.py` | No |
| `LogsTab` and `TraceDebugger` UI | `frontend/src/pages/AgentsPage.tsx` (logs tab) + `frontend/src/components/Dashboard/TraceDebugger.tsx` | **No change planned** | Low | ➕ render test feeding a delegation tree | No |
| Energy / power telemetry chain | `src/openjarvis/telemetry/energy_*.py` + `instrumented_engine.py` | **No change planned** | Low | ✅ existing telemetry tests | No |
| "Dollars Saved vs." panel | `frontend/src/pages/AgentsPage.tsx:6519-6593` | **No change planned** | Low | ➕ snapshot test for the panel | No |

## 5. Channels, connectors, sessions

| Feature | Implementation area | Proposed Phase 2 impact | Risk | Test coverage needed | Migration needed? |
|---|---|---|---|---|---|
| `channel_bindings` table + routing_mode | `agents/manager.py:45-53` | **No change planned** — Phase 2 may join `channel_bindings.session_id` with new `task_session_id`, but the binding table itself is untouched. | Low | ✅ existing channel-binding tests | No |
| All 16+ channel implementations | `src/openjarvis/channels/` | **No change planned** | Low | ✅ per-channel tests under `tests/connectors/` and channel modules | No |
| 30+ data connectors (Gmail/Drive/Calendar/RSS/Notion/Linear/GitHub/…) | `src/openjarvis/connectors/` | **No change planned** | Low | ✅ `tests/connectors/` | No |
| `SessionStore` + `SessionIdentity` (cross-channel user identity) | `src/openjarvis/sessions/session.py` | **Additive only** — Phase 2 may add a `task_session_id` column to `agent_tasks` referencing a session; no change to `SessionStore` itself. | Medium | ➕ test that a delegated task gets an isolated session and that the parent session is unaffected | Light (new column on `agent_tasks` only) |

## 6. Projects + Mission Control

| Feature | Implementation area | Proposed Phase 2 impact | Risk | Test coverage needed | Migration needed? |
|---|---|---|---|---|---|
| Projects store (categories, milestones, statuses) | `src/openjarvis/projects/store.py` | **No change planned** | Low | ✅ existing tests | No |
| Project tools (`project_create`, `project_create_task`, …) | `src/openjarvis/tools/project_tools.py` | **No change planned** | Low | ✅ `tests/tools/test_project_tools.py` | No |
| Mission Control fetcher / panel | `frontend/src/components/MissionControl/`, `frontend/src/lib/api.ts:fetchMissionControl` | **Additive only** — may render a small "live operational summary" header sourced from the new `task.*` events. | Low | ➕ render test | No |
| `ProjectsPage`, `ProjectDashboardPage`, `ProjectDetailPage`, `ProjectTimelinePage` | `frontend/src/pages/` | **No change planned** | Low | ➕ minimal mount-only smoke tests if not present | No |
| `project-status-report` skill (recent commit `e67d541b`) | skill registry | **No change planned** | Low | ✅ skill tests | No |

## 7. Voice surface

| Feature | Implementation area | Proposed Phase 2 impact | Risk | Test coverage needed | Migration needed? |
|---|---|---|---|---|---|
| `/v1/speech/stream` WebSocket | server + `frontend/src/hooks/useStreamingSpeech.ts` | **No change planned** | Medium (live UX) | ✅ speech tests | No |
| Multi-backend TTS discovery | `src/openjarvis/speech/_tts_discovery.py` | **No change planned** | Low | ✅ `tests/speech/test_tts_backends.py` | No |
| TTS player hook | `frontend/src/hooks/useTTSPlayer.ts` | **No change planned** | Low | ➕ optional snapshot test | No |
| STT / VAD / Whisper / Deepgram | `pyproject.toml:120-125` extras | **No change planned** | Low | ✅ existing speech tests | No |

## 8. Desktop wrapper + UX shell

| Feature | Implementation area | Proposed Phase 2 impact | Risk | Test coverage needed | Migration needed? |
|---|---|---|---|---|---|
| Tauri shell + plugins | `frontend/src-tauri/` | **No change planned** | Low | (manual) | No |
| Setup wizard / onboarding | `frontend/src/components/setup/`, `SetupScreen.tsx`, `GetStartedPage.tsx` | **No change planned** | Low | ➕ optional smoke | No |
| Command palette | `frontend/src/components/CommandPalette.tsx` | **No change planned** | Low | ➕ optional smoke | No |
| System pulse widget, OptInModal | `frontend/src/components/SystemPulse.tsx`, `OptInModal.tsx` | **No change planned** | Low | ➕ optional smoke | No |

## 9. Engines, mining, sandbox, security, learning

| Feature | Implementation area | Proposed Phase 2 impact | Risk | Test coverage needed | Migration needed? |
|---|---|---|---|---|---|
| All `InferenceEngine` backends (foundation) | `src/openjarvis/engine/` | **No change planned** | Low | ✅ existing engine tests | No |
| Mining / Pearl | `src/openjarvis/mining/` | **No change planned** | Low | ✅ existing | No |
| Engine availability dot (Ollama probe) | `frontend/src/pages/AgentsPage.tsx:2150-2210` | **No change planned** | Low | ➕ probe-mock unit test | No |
| `SandboxedAgent` + mount allowlist | `src/openjarvis/sandbox/` | **No change planned** — Phase 2 approval flow may *invoke* the sandbox more for `requires_approval` tools, but the sandbox contract itself is unchanged. | Low | ✅ existing sandbox tests | No |
| Security guardrails / scanners / audit log / subprocess sandbox / taint | `src/openjarvis/security/` | **No change planned** | Low | ✅ existing | No |
| Trace-driven router policy, distillation | `src/openjarvis/learning/` | **No change planned** | Low | ✅ existing | No |
| Scheduler + MCP scheduler tools | `src/openjarvis/scheduler/` | **Adapter possible (not required)** — Phase 2 *may* layer a background-task executor on top of the scheduler; if it does, existing cron jobs are not affected. | Medium | ➕ test that a scheduled job continues to fire independently of any new task executor | No |
| `agent_learning_log` table + LearningTab | `agents/manager.py:79-88` + frontend | **No change planned** | Low | ✅ existing | No |
| First-run setup scripts (`start.bat`, `stop.bat`, `Start_Claude_AI.bat`) | repo root | **No change planned** (any first-run setup that becomes necessary goes here, not as one-off commands) | Low | (manual) | No |

## 10. Recently-added (immediately-prior turn)

| Feature | Implementation area | Proposed Phase 2 impact | Risk | Test coverage needed | Migration needed? |
|---|---|---|---|---|---|
| Per-agent personality field | `src/openjarvis/server/managed_agent_runtime.py:276` + `frontend/src/pages/AgentsPage.tsx` (`AgentPersonalitySection`) | **No change planned** — personality block layers cleanly inside the system-prompt builder; Chief routing leaves it intact. | Low | ✅ `tests/server/test_managed_agent_prompting.py::test_managed_system_prompt_includes_personality` | No |

---

## 11. Risk summary

- **High-risk surfaces** (touch only behind a Change Impact Notice):
  `/v1/chat/completions` and `/v1/managed-agents/{id}/messages` ingress
  routes; `/v1/agents/events` WebSocket frame shape; `InterAgentActivityPanel`
  sidebar; `enrich_agent_record` JSON shape.
- **Medium-risk surfaces** (additive expected, but cross-cutting):
  `agent_tasks` schema; task status vocabulary; capability resolution
  return shape; scheduler-as-executor wiring; session ↔ task linkage.
- **Low-risk surfaces**: everything else listed, predominantly because
  Phase 2 has no planned touch on those modules.

## 12. Test gaps to close in Phase 2

The tests below do not exist today and **must** be added alongside any
Phase 2 work that touches the related area:

1. JSON contract test on `enrich_agent_record` output shape.
2. WebSocket frame-shape contract test on `/v1/agents/events`.
3. SSE event-name contract test on `/v1/chat/completions`.
4. Capability resolution tests for `inherited_*`, `blocked_*`,
   `requires_approval_*`.
5. Snapshot tests for `StatusBadge` (per agent and per task status).
6. `InterAgentActivityPanel` render tests per filter mode and per new
   `task.*` / `approval.*` event.
7. `ChiefPendingCard` test that an `awaiting_input` task surfaces in the
   card.
8. Migration test that pre-existing `agent_tasks` rows remain readable
   after additive ALTER TABLE.
9. Task-status mapping round-trip tests (legacy ↔ canonical).
10. Behavioral parity test: synchronous-run vs enqueued-run of
    `managed_agent_assign_task` produces the same observable result.
11. Isolation test: delegated task gets a session id distinct from the
    parent; parent session is unaffected.
12. Approval-flow tests: tool with `requires_approval` blocks until an
    approval is granted; denial path; timeout path.

---

## 13. Reminder of the change-control rule

This matrix is a forecast, not authorization. Any change that lands in
the "Breaking — needs Notice" column above must produce
`docs/CHANGE_IMPACT_NOTICES/<slug>.md` and **stop for explicit user
approval** before implementation, per `AGENTS.md` § "Change-control
protocol".
# Agent Assigned Jobs

| Feature | Protected behavior | Preservation rule | Validation |
| --- | --- | --- | --- |
| Per-agent jobs | Jobs are created, listed, paused/resumed, deleted, and run from the selected agent context. | Do not move jobs to a global-only surface or detach them from `managed_agents`. | `tests/agents/test_scheduler.py::TestSchedulerBasic::test_job_fire_creates_tracked_task_and_run` |
| Cron job display | Cron expression stays raw in persistence while next-run display is localized in the browser. | Do not persist user-localized display strings as the job schedule source of truth. | Frontend build/typecheck |
| Job run ledger | Every job fire creates an append-only run record with status, task link, summary/error, and event metadata. | Do not replace run history with mutable UI state. | Scheduler regression test |
| Chief/delegation path | Fired jobs materialize tracked agent work and attribute assignment to the designated Chief when available. | Do not execute scheduled jobs as direct human-facing subordinate ingress. | Scheduler regression test |
| Job capabilities | Job permissions appear in capability axes and include create/update/run/delegate semantics. | Do not hard-code job permission state only in the UI. | Frontend build/typecheck |
| App-event IFTTT jobs | Conditional jobs fire from app events such as login, logoff, task/project start, and task/project completion, plus registered custom events. | Do not turn IFTTT jobs into UI-only polling or hard-coded event lists. | `tests/agents/test_scheduler.py::TestSchedulerBasic::test_ifttt_job_fires_from_app_event` |

# Personal Life Manager Agent Templates

| Feature | Protected behavior | Preservation rule | Validation |
| --- | --- | --- | --- |
| Personal Life Manager templates | Built-in templates for `life_manager`, `sermon_study`, `health_routine`, `finance_reminder`, and `learning_coach` are available from the template catalog. | Do not remove or rename these templates without an approved Change Impact Notice. | `tests/integration/test_agent_manager_e2e.py::TestResearchMonitorE2E::test_personal_life_manager_templates_available` |
| Personal agent governance | Instantiated personal agents remain subordinate to Chief routing and capability policy. | Do not make these agents direct final human-facing ingress paths. | Template prompt review plus Chief ingress regression tests for touched routing surfaces. |
| Personal routines/reminders | Personal reminders and routines use durable Agent Jobs and task ledgers. | Do not replace them with mutable UI-only reminder state. | Scheduler/job regression tests for any preset implementation. |
| Personal Planning Dashboard | `/life-planner` derives Today, week, month, long-term, domain, routine, reminder, and notebook views from existing durable project/task/job sources. | Do not introduce a UI-only canonical reminder/habit store or bypass existing task/job ledgers. | `frontend/src/pages/personalPlanningUtils.test.ts` plus frontend build/typecheck. |
