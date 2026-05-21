# Architecture Drift Report

> **Status:** Phase 1 audit artifact, generated 2026-05-20.
> **Scope:** Read-only audit of the current Jarvis codebase against the
> `AGENTS.md` canonical guide and the user's stated north-star (Hermes /
> OpenClaw-style hierarchical chain of command on top of the OpenJarvis
> foundation).
> **Status of this document:** facts, not a plan. Phase 2 will turn the
> remediation hooks at the bottom into a phased, additive-first plan.

---

## 1. Methodology

Three parallel read-only audits were run against the codebase rooted at
`F:\Web Projects\Jarvis`, covering:

1. Chain-of-command runtime: Chief, hierarchy, task ledger, sessions,
   delegation, background execution.
2. Observability: event bus, SSE/WebSocket streams, traces, telemetry,
   approvals/security gating, capability resolution.
3. Frontend experience plane: ingress routes, agent overview, sidebar log,
   capability editor, status badges.

Every claim below cites a file and a line. The canonical spec being compared
against is `AGENTS.md` at the repo root (mirror of `CLAUDE.md`).

---

## 2. OpenJarvis foundation alignment — what we still follow

These are areas where the project still cleanly inherits its OpenJarvis
foundation and should be preserved unchanged:

| Foundation principle | Where it lives | Verdict |
|---|---|---|
| Decorator-based registries (`@AgentRegistry.register`, etc.) | `src/openjarvis/core/registry.py`, used by `agents/orchestrator.py:32-33`, all engines, tools, channels | **Intact** |
| `BaseAgent` ABC + `ToolUsingAgent` intermediate | `src/openjarvis/agents/_stubs.py` | **Intact** |
| `InferenceEngine` ABC with multi-backend discovery + fallback | `src/openjarvis/engine/_discovery.py` | **Intact** |
| EventBus pub/sub as cross-primitive connective tissue | `src/openjarvis/core/events.py:100-150` (synchronous dispatch in registration order) | **Intact** |
| Memory primitive with pluggable backends | `src/openjarvis/memory/` (SQLite/FTS5 default, FAISS, ColBERTv2, BM25, Hybrid) | **Intact** |
| Trace primitive: append-only SQLite with `parent_trace_id` + `run_id` | `src/openjarvis/traces/store.py:81-250` (WAL mode, FTS) | **Intact** |
| Telemetry primitive: per-model/engine/agent records, energy capture | `src/openjarvis/telemetry/`, `core/types.py:128-171` | **Intact** |
| Local-first runtime (Ollama/vLLM/SGLang/llama.cpp/MLX/Cloud) | `src/openjarvis/engine/` | **Intact** |
| API/UI/desktop separation | `server/`, `frontend/`, `frontend/src-tauri/` | **Intact** |

These align with the "Preserve the OpenJarvis-style foundation" rule. None of
the Phase 2 work should touch these contracts.

---

## 3. Hermes / OpenClaw-like behavior already present

Important: **the project has already moved meaningfully toward the desired
hierarchical model.** A rewrite is not needed — the missing pieces are
mostly enforcement, schema completeness, and UI policy surfacing.

| Capability | Where it lives | Notes |
|---|---|---|
| Chief decision envelope | `src/openjarvis/agents/chief.py:1-34` — `OrchestratorAction` dataclass with `COMPLETE`, `DELEGATE`, `EXECUTE_DIRECT`, `ASK_USER`, `FAIL` | Already structured like a Hermes-style orchestrator action loop. |
| Chief execution mode | `src/openjarvis/agents/orchestrator.py:97` — `if self._mode == "chief": return self._run_chief(...)` | Mode-flag on the existing OrchestratorAgent, not a separate class. |
| Hierarchy storage | `src/openjarvis/agents/manager.py:17-29` — `managed_agents.manager_agent_id` parent pointer with cycle validation (`_validate_manager_assignment`) | Solid foundation; missing only role/profile typing. |
| Delegation tools (least-privilege optional) | `src/openjarvis/tools/managed_agent_tools.py` — `managed_agent_delegate` (synchronous reply), `managed_agent_assign_task` (durable task + optional start), `managed_agent_directory` | `tools_allowed=` already passed through to constrain subordinate capabilities. |
| Per-trace delegation lineage | `traces/store.py` — `parent_trace_id` + `run_id` | Already supports rendering the full delegation tree. |
| Agent activity event stream | `core/events.py` — `AGENT_TICK_START/END/ERROR`, `AGENT_MESSAGE_RECEIVED`, `A2A_TASK_RECEIVED`, `A2A_TASK_COMPLETED`, `CAPABILITY_DENIED`, `AGENT_BUDGET_EXCEEDED`, `AGENT_STALL_DETECTED` | Most observability primitives exist. |
| WebSocket fan-out for agent events | `frontend/src/lib/useAgentEvents.ts:10-111` subscribing to `/v1/agents/events` with reconnect/backoff | Live operational feed is already wired end-to-end. |
| Right-side live agent activity log | `frontend/src/pages/AgentsPage.tsx:3814` — `InterAgentActivityPanel` (filter modes `all`/`active`/`alerts`/`direct`, polled history merged with live events) | This is the natural home for the "conversation log sidebar" required by `AGENTS.md`. |
| Org chart with live pulse | `frontend/src/pages/AgentsPage.tsx:3594` — `AgentOrgChart` with `connectorStyle()` animation when agents are active | Visualizes hierarchy + activity simultaneously. |
| Channel bindings (per-agent + routing_mode) | `agents/manager.py:45-53` — `channel_bindings(agent_id, channel_type, config_json, session_id, routing_mode)` | Per-agent messaging policy already exists. |
| Capability shape | `agents/capabilities.py:61-142` — `configured_*`, `effective_*`, `auto_tools`, `enrich_agent_record` | Distinction between *configured* and *effective* already modeled. |
| Templates + skills + presets | `agents/library.py`, `agents/templates/*.toml`, `skills/`, edited via `AgentPresetToolsSection` (`frontend/src/pages/AgentsPage.tsx:2565`) | Catalog + per-agent assignment + UI editor all present. |

---

## 4. Drift / conflicts with the chain-of-command model

These are the areas where the current code **conflicts** with
`AGENTS.md`. Each is sourced; none are speculative.

### 4.1 Chief is not the only human-facing ingress

`AGENTS.md` § "Chief Orchestrator is the only human-facing ingress" is **not
enforced**. Two ingress paths bypass the Chief today:

- **Chat page** → `POST /v1/chat/completions` (`frontend/src/lib/sse.ts:18`).
  This is the OpenAI-compatible endpoint; it accepts an optional `agent_id`
  in the body (`ChatRequest.agent_id?`) but there is no server-side
  enforcement that requests are routed through a Chief node first.
- **Agent-interact tab** → `POST /v1/managed-agents/{agentId}/messages`
  (`frontend/src/lib/api.ts:1136-1148`, via `sendAgentMessage`). The
  agentId is whatever agent the user clicked into; the InteractTab speaks
  to that agent directly.

**Conflict severity:** High. This violates the most-important invariant in
`AGENTS.md`.

### 4.2 Task schema is sparse relative to spec

`agent_tasks` (`agents/manager.py:32-42`) has:
`id, agent_id, assigned_by_agent_id, description, status, progress_json,
findings_json, created_at, project_task_id, project_id`.

`AGENTS.md` § "Task model" requires additionally:
`parent_id, root_id, request_source, requesting_user, priority, updated_at,
completed_at, summary, errors, requires_user_input, requires_approval`.

Hierarchy linkage is currently approximated through `assigned_by_agent_id`
(who delegated) and the optional `project_task_id`/`project_id`
(post-migration), but there is no explicit `parent_task_id` / `root_task_id`
chain on the task record itself.

### 4.3 Task status vocabulary mismatch

Actual values in the manager (`agents/manager.py:672+`, surfaced in
`frontend/src/lib/api.ts:492`):
`pending | active | completed | failed`.

`AGENTS.md` canonical state machine:
`received | triaged | planned | delegated | in_progress | blocked |
awaiting_input | awaiting_approval | completed | failed | cancelled`.

The agent runtime status vocabulary (`api.ts:465`) is much closer to the
spec (`idle | running | paused | error | archived | needs_attention |
budget_exceeded | stalled | input_required | auth_required |
waiting_on_tool`) — the *task* statuses are the ones lagging.

### 4.4 Missing task lifecycle and approval events

`core/events.py:21-79` has rich `agent.*`, `tool.*`, `memory.*`, `trace.*`,
`security.*`, `a2a.*` event types but **none of**:

- `task.created`, `task.updated`, `task.delegated`, `task.completed`,
  `task.failed`
- `approval.requested`, `approval.resolved`
- `ui.notification`

The streamed events surfaced over WebSocket `/v1/agents/events` therefore
carry agent-tick and tool-call signals but no first-class task lifecycle
signals. The frontend's `InterAgentActivityPanel` works around this by
listening for `agent_tick_*` and `agent_message_received` and synthesizing
task-level meaning from them.

### 4.5 No approval flow

`chief.py` defines an `ASK_USER` action but there is **no end-to-end
approval workflow**:

- No `approval_request` table.
- No `approval.requested` / `approval.resolved` events.
- No per-tool `requires_approval` flag.
- No server route to approve/deny a pending action.
- No UI affordance to render an approval prompt sourced from the event
  stream (input prompts are handled per-agent via `Chief Pending Card`
  ≈ `AgentsPage.tsx:2293`, but that is a free-text question/response, not a
  policy-gated approval).

`src/openjarvis/security/` (`guardrails.py`, `file_policy.py`,
`subprocess_sandbox.py`, `taint.py`) provides **scanners** — defense in
depth — not a user-in-the-loop approval gate.

### 4.6 Capability inheritance & blocks are not modeled

`agents/capabilities.py:105-125` computes `effective_tool_names` as
`configured + auto-injected` (collaboration tools always, project tools for
managers, knowledge tools for `deep_research`). There is no:

- **inherited from manager** axis (a manager's policy does not propagate);
- **blocked / denylist** axis;
- **approval-required** per-capability flag.

`AGENTS.md` § "Capability inheritance" requires a 5-layer resolution
(system → role → manager → agent-local → task-scoped) and the UI to
distinguish `available / assigned / inherited / effective / disabled /
protected`. The current `AgentPresetToolsSection`
(`frontend/src/pages/AgentsPage.tsx:2565`) renders configured/effective
chips but does not surface inheritance or block state.

### 4.7 Delegation is synchronous; no resumable background execution

`managed_agent_tools.py:362-370` — the `managed_agent_delegate` tool calls
`ctx.runtime.run(...)` synchronously; the delegator blocks until the
subordinate returns. `managed_agent_assign_task` can create a durable task
record but `start_now=True` (default) immediately calls `ctx.runtime.run`
inline as well.

`AGENTS.md` § "background execution" requires durable, resumable child
tasks. The scheduler (`src/openjarvis/scheduler/`) handles cron-style jobs
but is not wired as a delegation execution queue.

### 4.8 Worker sessions are not isolated from the Chief session

`sessions/session.py` provides cross-channel user-identity consolidation;
`channel_bindings.session_id` ties a binding to a session, but **agent
tasks are not joined to sessions**. There is no per-task isolated worker
session, so long-running subordinate work shares context with the parent.

### 4.9 EventBus is not append-only by default

`core/events.py:108` — `record_history` is an opt-in flag at bus
construction. The default bus does not retain history; replay relies on
TraceStore (which is append-only) for inference/tool/memory events but
**not for agent-to-agent handoffs or approvals**.

### 4.10 UI capability editor lacks policy surfacing

`AgentPresetToolsSection` is rich but does not visually distinguish the
six categories `AGENTS.md` requires (`available / assigned / inherited /
effective / disabled / protected`). Today: configured chips vs auto
("effective") chips, no inheritance/block/protected affordance.

### 4.11 Convention nit: change-notice path

`AGENTS.md` mandates `docs/CHANGE_IMPACT_NOTICES/<slug>.md` (folder), the
user's Phase 3 instruction names `docs/CHANGE_IMPACT_NOTICE_<slug>.md`
(prefix). These resolve to different filesystem locations. **I am following
the `AGENTS.md` convention** (folder) since it's the canonical in-repo
guide and matches the rest of the doc's structure. Flag if you want the
flat-prefix form instead.

---

## 5. Cross-cutting summary table

| Spec area (`AGENTS.md`) | Implemented? | Where | Severity if missing |
|---|---|---|---|
| Chief as sole ingress | ❌ | n/a | **High** — invariant violation |
| Hierarchy storage | ✅ | `manager.py:17-29` | — |
| Task model fields | 🟡 partial | `manager.py:32-42` | Medium |
| Task status vocab | ❌ | `manager.py` (4-state) vs 11-state spec | Medium |
| `task.*` events | ❌ | `core/events.py` | Medium |
| `approval.*` events + flow | ❌ | n/a | Medium |
| Append-only event log | 🟡 (traces only) | `traces/store.py` | Medium |
| Live activity stream | ✅ | `useAgentEvents.ts` + `InterAgentActivityPanel` | — |
| Per-trace delegation lineage | ✅ | `traces/store.py` | — |
| Telemetry per agent/model/engine | ✅ | `telemetry/` | — |
| Capability inheritance | ❌ | `capabilities.py` | Medium |
| Capability block / approval-required | ❌ | `capabilities.py` | Medium |
| Capability inspector UI states | 🟡 partial | `AgentPresetToolsSection` | Low–Medium |
| Background / resumable delegation | ❌ | synchronous only | Medium |
| Per-task worker session isolation | ❌ | sessions store user identity, not tasks | Medium |
| Org chart UI | ✅ | `AgentOrgChart` | — |
| Sidebar event log UI | ✅ | `InterAgentActivityPanel` | — |
| OpenJarvis foundation primitives | ✅ | `core/`, `engine/`, `memory/`, `traces/`, `telemetry/` | Must preserve |

---

## 6. Remediation hooks (informational only — Phase 2 will plan from these)

This section lists *where* the Phase 2 plan would most cleanly bolt onto
the existing system. **No edits are proposed here yet.** All Phase 2
proposals will live in their own document and follow the additive-first
rule.

| Drift | Cleanest landing point | Why |
|---|---|---|
| Chief-as-ingress | Server-side: a `/v1/chief/messages` router that loads the user's Chief and delegates internally. Frontend: keep `/v1/chat/completions` for OpenAI-compatible third-party use; route `ChatPage` + `InteractTab` through the new endpoint. Old endpoint can stay (additive). | Avoids breaking the OpenAI-compatible surface. |
| Task schema | Additive ALTER TABLE adding `parent_task_id`, `root_task_id`, `request_source`, `requesting_user`, `priority`, `updated_at`, `completed_at`, `summary`, `errors_json`, `requires_user_input`, `requires_approval`. Back-fill at migration time. | Existing rows continue to work; new fields are nullable. |
| Status vocabulary | Introduce canonical status type in `core/types.py`; map current `pending/active/completed/failed` → canonical at the read boundary; write canonical going forward; UI consumes canonical. | Backwards-compatible mapping layer keeps existing rows valid. |
| `task.*` + `approval.*` events | Add to `EventType` enum; emit from `manager.py` task lifecycle calls + a new approval module; surface in `useAgentEvents.ts` (no new transport required). | Reuses existing WebSocket fan-out. |
| Approval flow | New `approvals` table + `/v1/approvals` routes + `requires_approval` capability flag honored in tool dispatch. UI: render approval requests in `InterAgentActivityPanel` and as a CTA on the agent detail Overview. | Builds on the existing event/sidebar infrastructure. |
| Capability inheritance / blocks | Extend `capabilities.py` with `inherited_*`, `blocked_*`, `requires_approval_*`. UI: extend `AgentPresetToolsSection` with badges for the six states. | The data layer already separates configured vs effective; this is one more axis. |
| Background delegation | Wrap `managed_agent_assign_task` with an executor queue (could re-use the scheduler) + change `start_now=True` default behavior to enqueue rather than block. | The durable task table already exists. |
| Worker session isolation | Add a `task_session_id` to the task table; child sessions cloned from parent only at the point of delegation. | Sessions module already exists. |

---

## 7. Bottom line

- The OpenJarvis foundation is intact and should not be touched.
- The project has already taken substantial steps toward the Hermes/OpenClaw-
  style hierarchical model: a Chief action envelope, delegation tools, a
  hierarchy table, a live agent-events WebSocket, an `InterAgentActivityPanel`
  sidebar, and per-agent capability shape.
- The drift is concentrated in **enforcement and schema completeness**, not
  primitives. A rewrite is unnecessary; a phased additive refactor will get
  to compliance.
- The two highest-severity items are (1) Chief-as-sole-ingress and (2) the
  task model / status vocabulary gap. Everything else is medium severity
  and can be done as additive changes behind compatibility shims.
