# Hierarchical Agent Implementation Plan

> Status: Phase 2 plan. This is additive-first and does not approve breaking changes.
> Inputs: `AGENTS.md`, `docs/ARCHITECTURE_DRIFT_REPORT.md`, `docs/AUGMENTED_FEATURES.md`, and `docs/FEATURE_PRESERVATION_MATRIX.md`.

## Phase 0: Guardrails and Contracts

- Goal: make the existing rules executable for future work.
- Touched files/modules: `AGENTS.md`, `docs/CHANGE_IMPACT_NOTICES/`, test docs.
- New types/schemas/events: none.
- Tests to add: none for docs-only setup.
- User-visible effect: future Codex runs have a clear approval gate and protected-feature inventory.
- Rollback plan: revert docs-only changes.

## Phase 1: Chief Ingress Adapter

- Goal: route Chat Page and Agent Interact work through a Chief-owned ingress without removing existing endpoints.
- Touched files/modules: `src/openjarvis/server/agent_manager_routes.py`, `src/openjarvis/server/api_routes.py`, `src/openjarvis/server/managed_agent_runtime.py`, `frontend/src/lib/api.ts`, `frontend/src/lib/sse.ts`, `frontend/src/pages/ChatPage.tsx`, `frontend/src/pages/AgentsPage.tsx`.
- New types/schemas/events: `request_source`, `chief_agent_id`, `root_task_id` request metadata.
- Tests to add: server integration tests for Chat Page -> Chief and Interact Tab -> Chief; regression tests proving `/v1/chat/completions` and direct managed-agent routes still work.
- User-visible effect: user-facing work is presented by the Chief while legacy/power-user routes remain available.
- Rollback plan: feature flag frontend routing back to current direct routes.

## Phase 2: Durable Task Ledger Extensions

- Goal: extend current `agent_tasks` into a root/child task ledger with stable status transitions.
- Touched files/modules: `src/openjarvis/agents/manager.py`, `src/openjarvis/core/types.py`, `frontend/src/lib/api.ts`, task UI sections.
- New types/schemas/events: nullable `parent_task_id`, `root_task_id`, `request_source`, `requesting_user`, `priority`, `updated_at`, `completed_at`, `summary`, `errors_json`, `requires_user_input`, `requires_approval`; canonical task statuses.
- Tests to add: migration/backfill tests, status mapping tests, task lifecycle unit tests, UI status rendering tests.
- User-visible effect: tasks show richer progress, failure, blocked, input-needed, and approval-needed states.
- Rollback plan: keep old columns and status strings readable; feature flag canonical status display.

## Phase 3: Structured Event Journal

- Goal: add task and approval events to the existing event bus and WebSocket surface.
- Touched files/modules: `src/openjarvis/core/events.py`, agent manager task mutations, managed runtime, WebSocket event routes, `frontend/src/lib/useAgentEvents.ts`, `InterAgentActivityPanel`.
- New types/schemas/events: `task.created`, `task.updated`, `task.delegated`, `task.completed`, `task.failed`, `approval.requested`, `approval.resolved`, `ui.notification`.
- Tests to add: event emission unit tests, WebSocket frame-shape tests, sidebar rendering tests.
- User-visible effect: the Agents sidebar shows delegation, progress, tool milestones, errors, completions, and approvals from runtime events.
- Rollback plan: keep existing `agent_tick_*` and `agent_message_received` consumers untouched.

## Phase 4: Capability Policy Resolution

- Goal: make skills, presets, tools, and datasources policy-driven per agent.
- Touched files/modules: `src/openjarvis/agents/capabilities.py`, managed-agent APIs, capability editor UI, related tests.
- New types/schemas/events: assigned, inherited, effective, blocked, approval-required capability fields.
- Tests to add: unit tests for inheritance, blocks, approvals, task-scoped overrides; API contract tests.
- User-visible effect: capability editor distinguishes assigned, inherited, effective, disabled, protected, and approval-required capabilities.
- Rollback plan: preserve current `configured_*`, `effective_*`, `auto_tools`, and `knowledge_enabled` API keys.

## Phase 5: Background Delegation and Worker Sessions

- Goal: make subordinate work durable and resumable where practical.
- Touched files/modules: `src/openjarvis/tools/managed_agent_tools.py`, `src/openjarvis/agents/manager.py`, `src/openjarvis/sessions/session.py`, scheduler/runtime modules.
- New types/schemas/events: `task_session_id`, queue/executor state, background lifecycle events.
- Tests to add: delegation parity tests, worker-session isolation tests, resume/recovery tests, scheduler regression tests.
- User-visible effect: long-running child work can continue in the background and report status upward.
- Rollback plan: keep synchronous delegation path behind a compatibility flag.

## Phase 6: Approval Flow

- Goal: gate destructive and security-sensitive actions through explicit policy or user approval.
- Touched files/modules: security policy modules, tool dispatch path, agent manager routes, event stream, Agents sidebar.
- New types/schemas/events: approval request records, approval decision records, `requires_approval` capability metadata.
- Tests to add: approval grant, denial, timeout, and audit-log tests.
- User-visible effect: risky actions appear as explicit approval requests instead of running silently.
- Rollback plan: keep existing scanner/guardrail behavior and enable approval enforcement per capability class.

## Phase 7: Regression Hardening

- Goal: prove protected features still work.
- Touched files/modules: tests for protected surfaces listed in `docs/AUGMENTED_FEATURES.md`.
- New types/schemas/events: none.
- Tests to add: regression tests for touched routes, UI tabs, channels, projects, telemetry, traces, voice, desktop-adjacent APIs, and capability editor behavior.
- User-visible effect: no intentional feature loss.
- Rollback plan: disable new feature flags and retain compatibility adapters.

## Approval Checkpoints

Create `docs/CHANGE_IMPACT_NOTICES/<slug>.md` and stop before any step that:
- removes or disables a protected feature,
- changes a public API contract,
- changes persistence shape in a non-additive way,
- changes a user workflow without fallback,
- replaces a subsystem,
- makes subordinate agents directly user-facing for final completion.
# Addendum: Agent Assigned Jobs

Approved implementation added an additive Agent Jobs layer:
- `agent_jobs` stores durable per-agent job definitions.
- `agent_job_runs` stores append-only run history.
- Job firing materializes tracked agent work and attributes it through the Chief when designated.
- Jobs carry required capabilities and delegation policy so scheduled work can participate in the same capability/delegation model as agent tasks.
- IFTTT jobs subscribe to app events, including login/logoff, task start/completion, project start/completion, and custom events registered through the app-event API.
- Agent Overview includes a Jobs tab for creation and operations.
- Existing agent schedule config remains intact for backward compatibility.

Next hardening steps:
- Broaden `if_this_then_that` predicates with explicit allowlisted payload condition evaluators.
- Add approval gates for destructive job actions and high-risk delegated capabilities.
- Add richer UI editing for existing job definitions and job run history drill-down.
