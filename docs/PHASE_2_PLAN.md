# Phase 2 — Implementation Plan

> **Status:** Phase 2 artifact, generated 2026-05-20.
> **Sources of truth:** `AGENTS.md`, `docs/ARCHITECTURE_DRIFT_REPORT.md`,
> `docs/AUGMENTED_FEATURES.md`, `docs/FEATURE_PRESERVATION_MATRIX.md`, and
> the user-supplied Capability Inspector + Agents Page design proposal
> (treated as the canonical design for Phase 2B; cited inline as
> **"the proposal"**).
> **This document is a plan, not authorization.** Phases marked
> **NEEDS CIN** stop and wait for a Change Impact Notice + explicit
> approval before any code is written.

---

## Sequencing principles

1. **Additive-first.** No data shape, API contract, or user workflow
   changes in phases 2A–2D. Each lands behind feature flags where the
   behavior is observable.
2. **Foundations before UI.** Phase 2A puts the data and event plumbing
   in place that 2B–2D depend on, so the UI never reaches for a field
   that doesn't exist yet.
3. **Capability Inspector (proposal) is the centerpiece of 2B.** But it
   ships on top of the broader foundation, not in isolation.
4. **The two highest-severity drift items** — Chief-as-sole-ingress (drift
   §4.1) and the task model gap (drift §4.2/§4.3) — are split: the *schema
   half* lands additively in 2A, the *enforcement half* (changing default
   routing) is deferred to 2E and gated on a CIN.
5. **Background execution (2F) and worker session isolation (2G)** are
   gated on a CIN because they change the behavior of an existing tool
   (`managed_agent_assign_task`) even though the schema is unchanged.

The exact order below is the recommended order. 2C/2D can swap order;
2E/2F/2G can be reordered after their CINs are approved.

---

## Phase 2A — Foundational additions (purely additive)

**Goal.** Land every data, event, and computation primitive that 2B–2D
depend on, without changing any current behavior. After 2A, the system
behaves exactly as it does today — only with more nullable columns, more
unused event types, and richer optional output fields.

**Touched files / modules.**
- `src/openjarvis/core/types.py` — canonical status enum + bidirectional
  mapper.
- `src/openjarvis/core/events.py` — new `EventType` values; emitters not
  wired yet.
- `src/openjarvis/agents/manager.py` — ALTER TABLE on `agent_tasks`;
  new `agent_config_versions` table; helper functions for both.
- `src/openjarvis/agents/capabilities.py` — extend
  `enrich_agent_record()` with optional new keys; new resolution helper
  `resolve_capability_axes(agent, manager_record=None)`.
- `src/openjarvis/server/agent_manager_routes.py` — new endpoint
  `POST /v1/managed-agents/{id}/preview` returning computed effective
  capabilities and the resolved axes, without saving.
- `tests/agents/`, `tests/server/`, `tests/core/` — new tests per below.

**New types / schemas / events.**

| Item | Where | Notes |
|---|---|---|
| `TaskStatus` canonical enum (`received`, `triaged`, `planned`, `delegated`, `in_progress`, `blocked`, `awaiting_input`, `awaiting_approval`, `completed`, `failed`, `cancelled`) | `core/types.py` | Plus `map_legacy_status(str) -> TaskStatus` and `to_legacy(TaskStatus) -> str` for read/write boundary. |
| New nullable columns on `agent_tasks` | `manager.py:32-42` | `parent_task_id`, `root_task_id`, `request_source`, `requesting_user`, `priority`, `updated_at`, `completed_at`, `summary`, `errors_json`, `requires_user_input`, `requires_approval`, `task_session_id`. All NULL-OK. Existing rows back-fill on read. |
| `agent_config_versions` table | `manager.py` | `(version_id PK, agent_id FK, version_number, diff_json, snapshot_json, created_at, created_by)`. Append-only. Written on `update_agent` when `config` changes. |
| `EventType.TASK_CREATED / TASK_UPDATED / TASK_DELEGATED / TASK_COMPLETED / TASK_FAILED` | `core/events.py` | Enum values only; no emitters wired in 2A. |
| `EventType.APPROVAL_REQUESTED / APPROVAL_RESOLVED` | `core/events.py` | Enum values only. |
| `EventType.UI_NOTIFICATION` | `core/events.py` | Enum value only. |
| New keys on `enrich_agent_record()` output | `capabilities.py:128-142` | `inherited_skills`, `inherited_tools`, `blocked_skills`, `blocked_tools`, `requires_approval_skills`, `requires_approval_tools`. Today all return empty lists (resolver lands in 2A but inheritance graph is empty until 2B/2D actually populate manager-imposed policy). Existing keys keep semantics. |
| `POST /v1/managed-agents/{id}/preview` | `agent_manager_routes.py` | Body: optional `config_overrides`. Returns: full enriched record + axes, without persisting. Idempotent. |

**Tests to add.**
1. `tests/core/test_task_status.py` — round-trip mapper for each legacy
   value, unknown legacy value falls back to `received` with a logged
   warning.
2. `tests/agents/test_manager_task_schema_migration.py` — pre-existing
   `agent_tasks` rows readable after ALTER; new columns default NULL;
   new task insertions populate them.
3. `tests/agents/test_agent_config_versions.py` — `update_agent` with a
   `config=` change writes a version row; a no-op update writes nothing;
   `get_agent_versions(id)` returns rows in order.
4. `tests/core/test_event_types.py` — new `EventType` values exist; bus
   `subscribe` to them works; no crash when nothing emits.
5. `tests/agents/test_capabilities_axes.py` — `enrich_agent_record`
   returns the new keys as empty lists when no policy exists; existing
   keys still present with current semantics.
6. `tests/server/test_preview_endpoint.py` — `POST /preview` returns the
   enriched record + axes; nothing persisted (verify via subsequent
   `GET`).
7. **Contract snapshot tests** for the existing `enrich_agent_record`
   output and for `/v1/agents/events` WebSocket frame shape — these
   guard the high-blast-radius surfaces flagged in the preservation
   matrix.

**User-visible effect.** None. The only externally observable change is
the new `/preview` endpoint (which the UI doesn't call yet).

**Rollback plan.** Each subtask is an independently revertable change:
- Status enum + mapper: revert is a single-file revert; no data touched.
- ALTER TABLE: rollback is `ALTER TABLE … DROP COLUMN` (or
  `PRAGMA writable_schema` if SQLite version forces it). New columns are
  nullable and unread, so dropping them is safe.
- `agent_config_versions`: `DROP TABLE`; no foreign keys point at it.
- New event types: revert removes enum members. No emitters depend on
  them.
- New `enrich_agent_record` keys: revert removes them. Frontend types
  stay `Record<string, unknown>`-tolerant.
- Preview endpoint: revert removes route; no data shape relies on it.

**Risk.** Low. All purely additive. The contract snapshot tests catch
accidental drift in existing surfaces.

---

## Phase 2B — Capability Inspector + Agents Page UI (additive; the proposal)

**Goal.** Land the proposal's Capability Inspector design (Concept 1 +
card grouping) as the new Overview-tab experience. Existing chips and
sections keep rendering; new badges, search/filter, drag-reorder, bulk
actions, preview modal, version history, and conflict warnings layer on
top.

**Touched files / modules.**
- `frontend/src/pages/AgentsPage.tsx` — extend
  `AgentPresetToolsSection`, add `CapabilityInspector`,
  `EffectiveCapabilitiesPreviewModal`, `AgentConfigHistoryDrawer`.
- `frontend/src/components/Sidebar/` — extend or reuse
  `InterAgentActivityPanel` filter state (no breaking change to its
  consumer API).
- `frontend/src/lib/api.ts` — `previewAgentCapabilities(id, overrides?)`,
  `fetchAgentConfigVersions(id)`, `revertAgentConfig(id, versionId)`.
- New: `frontend/src/lib/optimistic.ts` — small helper for the
  optimistic-update pattern from the proposal (state push, server call,
  rollback on error, toast).
- `frontend/src/components/ui/` — `Chip`, `Badge`, `SearchSelect`,
  `ConfirmDialog` primitives if not already present; reuse if they are.
- `src/openjarvis/server/agent_manager_routes.py` — additive routes
  `GET /v1/managed-agents/{id}/versions`, `POST /v1/managed-agents/{id}/revert`.

**New types / schemas / events.**

| Item | Where | Notes |
|---|---|---|
| `CapabilityAxis = 'assigned' \| 'inherited' \| 'effective' \| 'disabled' \| 'protected' \| 'requires_approval'` | `frontend/src/lib/api.ts` | Frontend shared enum mapping 1:1 to the axes returned by 2A's `enrich_agent_record`. |
| `Chip` badge variants | `frontend/src/components/ui/Chip.tsx` (or `Badge.tsx`) | Six variants matching the axes. |
| `GET /v1/managed-agents/{id}/versions` | `agent_manager_routes.py` | Returns array of `{version_id, version_number, created_at, created_by, summary, diff_json}`. |
| `POST /v1/managed-agents/{id}/revert` | `agent_manager_routes.py` | Body: `{version_id}`. Re-applies the snapshot as a new version (no destructive revert; history is preserved). |

**Tests to add.**
- `tests/server/test_versions_routes.py` — list/revert endpoints; revert
  creates a new version, doesn't truncate history.
- Frontend snapshot tests (Vitest or Playwright):
  `CapabilityInspector` per axis state, empty state, bulk-remove flow,
  preview modal, conflict-warning dialog when removing a datasource a
  skill depends on, drag-reorder of skill chips, version-history drawer
  render.
- Contract test: ensure existing PATCH `/v1/managed-agents/{id}` with a
  `config` blob still works (no replacement, just addition).

**User-visible effect.**
- New Capability Inspector layout on the agent detail Overview tab,
  matching the proposal's recommended design.
- Skill chips now show axis badges (`assigned` / `inherited` /
  `effective` / `disabled` / `protected` / `requires_approval`).
- "Preview Capabilities" button → modal listing effective skills +
  active tools, no save side-effect.
- "Version history" drawer with revert (revert appends a new version,
  preserving full history).
- Search/filter on skills + data sources; drag-to-reorder skill chips;
  multi-select bulk remove.
- Conflict warning dialog when removing a datasource a configured skill
  depends on.
- Existing `AgentInstructionSection`, `AgentPersonalitySection`,
  `AgentConfigGrid`, `AgentOrganizationSection`, and the savings panel
  **all remain visible and functional**.

**Rollback plan.**
- Frontend changes ship behind a `capability_inspector_v2` UI feature
  flag (per AGENTS.md "Required workflow"). Rollback flips the flag to
  show the existing `AgentPresetToolsSection`.
- New backend routes are additive; rollback removes the routes; no UI
  depends on them when the flag is off.

**Risk.** Medium for the JSON-contract surface
(`enrich_agent_record` output). Mitigated by the contract snapshot test
from 2A and by keeping the existing keys unchanged.

**Per the proposal, *not* implemented in 2B** (and why):
- `data_sources: [string]` as a first-class array on the agent record →
  defer; see "Open design questions" §1 below.
- `tools: [string]` stored on the agent record → defer; today computed
  via `effective_agent_tool_names()`. Storing it would create
  stored/computed drift.
- `preset` as a live first-class field → defer; today `template_id` is
  a one-shot scaffold. Promotion to a live binding is a behavioral
  change that needs a CIN.
- `version`, `created_by`, `updated_by` on the agent config blob → the
  *audit version table* covers history without changing the agent
  schema. We capture `created_by` / `updated_by` only inside the
  `agent_config_versions` row, not on the agent itself, until the
  project has a real user-identity model.

---

## Phase 2C — Task lifecycle events emission (additive)

**Goal.** Start emitting the `task.*` events declared in 2A from the
manager's task lifecycle calls, surface them on `/v1/agents/events`, and
render them in `InterAgentActivityPanel`. Status mapping (legacy ↔
canonical) flows through the events.

**Touched files / modules.**
- `src/openjarvis/agents/manager.py` — `create_task`, `update_task` and
  any internal call sites; emit `TASK_CREATED` / `TASK_UPDATED` /
  `TASK_COMPLETED` / `TASK_FAILED` on transitions.
- `src/openjarvis/tools/managed_agent_tools.py` —
  `managed_agent_delegate` and `managed_agent_assign_task` emit
  `TASK_DELEGATED` with `{parent_task_id, child_task_id,
  delegating_agent_id, target_agent_id}`.
- `src/openjarvis/server/` — the WebSocket fan-out at `/v1/agents/events`
  forwards the new event types.
- `frontend/src/lib/useAgentEvents.ts` — extend `AgentEvent` union.
- `frontend/src/pages/AgentsPage.tsx` — `InterAgentActivityPanel` renders
  the new event types under the existing filter modes (no new filter
  mode needed; they slot into `active` and `direct`).

**New types / schemas / events.** Same enum values declared in 2A; this
phase wires emitters and consumers.

**Tests to add.**
- `tests/agents/test_task_event_emission.py` — every transition path
  emits exactly one event of the expected type with the expected payload.
- `tests/server/test_agent_events_ws_task_events.py` — WebSocket frames
  carry the new event types.
- Frontend: `InterAgentActivityPanel` renders new event types per filter
  mode.

**User-visible effect.** The right-side activity sidebar starts
showing first-class task lifecycle entries (created / delegated /
completed / failed) in addition to the agent-tick and tool-call
entries it already shows.

**Rollback plan.** Each emitter is a one-line `bus.publish(...)`;
revert removes the line. UI rendering of unknown event types is a no-op
(existing fallback in `useAgentEvents`).

**Risk.** Low–Medium. Risk is concentrated in the WebSocket frame
shape, which the 2A contract snapshot test guards.

---

## Phase 2D — Approval flow (additive)

**Goal.** End-to-end approval gating for capabilities marked
`requires_approval`. Builds on 2A's event types and config axes, 2C's
task events, and 2B's UI.

**Touched files / modules.**
- New `src/openjarvis/agents/approvals.py` — `ApprovalStore`,
  `ApprovalRequest` dataclass.
- New `agent_approvals` table — `(id PK, task_id FK, agent_id FK,
  capability, args_json, requested_at, resolved_at, resolved_by,
  decision, reason)`.
- `src/openjarvis/agents/capabilities.py` — tool dispatch consults
  `requires_approval_*` axes; on hit, creates an approval request,
  transitions the task to `awaiting_approval`, emits
  `APPROVAL_REQUESTED`.
- New routes `GET /v1/approvals`, `POST /v1/approvals/{id}/grant`,
  `POST /v1/approvals/{id}/deny`.
- `frontend/src/pages/AgentsPage.tsx` — extend `ChiefPendingCard`
  (`AgentsPage.tsx:2293`) to render approval requests alongside its
  existing free-text question pattern; sidebar
  `InterAgentActivityPanel` renders `approval.*` events.

**New types / schemas / events.**

| Item | Where | Notes |
|---|---|---|
| `agent_approvals` table | `agents/approvals.py` migration | Append-only updates: `resolved_at`/`resolved_by`/`decision`/`reason` set once. |
| `EventType.APPROVAL_REQUESTED / APPROVAL_RESOLVED` | wired emitters | Declared in 2A; emitted here. |
| `ApprovalRequest` payload type on the WebSocket frame | `useAgentEvents.ts` | Carries `{task_id, agent_id, capability, args_summary}`; no secrets. |

**Tests to add.**
- `tests/agents/test_approvals.py` — tool with `requires_approval=true`
  creates an approval request and blocks the task in
  `awaiting_approval`; grant resumes; deny fails with reason; timeout
  path.
- `tests/server/test_approvals_routes.py` — grant/deny idempotent;
  authorization enforced (least-privilege; deny unauthorized callers).
- Frontend: `ChiefPendingCard` renders approval requests; sidebar
  badge counts.

**User-visible effect.** A tool flagged `requires_approval` now
surfaces a CTA on the agent detail card and a sidebar entry; the user
grants/denies; the task continues or fails.

**Rollback plan.** Each piece is a separate change; revert in reverse
order. The `agent_approvals` table is independent; drop is safe.
Tool-dispatch gating is feature-flagged (`approval_gating_enabled`)
defaulting to false until 2D ships.

**Risk.** Medium. New end-to-end flow with security implications.
Mitigation: deny-by-default for unauthorized grant/deny calls; ship the
default `requires_approval=true` flag empty (no capability requires
approval until an admin sets it).

---

## Phase 2E — Chief as canonical ingress (**NEEDS CIN**)

**Goal.** Make the Chief the default ingress for the chat page and the
agent-interact tab, without removing the OpenAI-compatible
`/v1/chat/completions` surface or the
`/v1/managed-agents/{id}/messages` direct-talk surface.

**Why CIN.** Even though the API surface itself is additive (new
`/v1/chief/messages` route, old routes preserved), **the default
user-facing routing behavior changes**. `ChatPage` and `InteractTab`
switch to call the new route by default. That's a workflow change per
AGENTS.md § "Change-control protocol" → "Required document for
breaking or risky changes".

**Outline of what the CIN will propose** (for context; not authorized):
- New route `POST /v1/chief/messages` that loads (or instantiates) the
  user's Chief and routes the message through `_run_chief` in
  `orchestrator.py:97`.
- `ChatPage` defaults to the Chief route; keeps a "Direct" power-user
  toggle that uses `/v1/chat/completions` unchanged.
- `InteractTab` adds a "Route through Chief" toggle, default ON for
  subordinates, OFF for the Chief itself.
- `/v1/chat/completions` (the OpenAI-compatible endpoint) **untouched**.
- Migration: existing agents without a designated Chief get one
  auto-created (mirroring whatever the user's current "default"
  org_role assignment is) at first load.

**Stop point.** No code; produce
`docs/CHANGE_IMPACT_NOTICES/chief-as-canonical-ingress.md` and wait.

---

## Phase 2F — Background delegation execution (**NEEDS CIN**)

**Goal.** `managed_agent_assign_task(start_now=True)` enqueues a
background execution instead of blocking the delegating agent.

**Why CIN.** Existing tool's observable behavior changes: today the
caller blocks until the subordinate returns; tomorrow it returns after
enqueue. Even with a feature flag, this is a behavioral change for an
existing tool surface (per AGENTS.md § "Forbidden behaviors": "never
silently degrade … a tool"). Needs explicit approval.

**Outline of what the CIN will propose:**
- Background executor — could re-use `scheduler/` infrastructure or be
  its own queue + worker pool.
- `start_now=True` semantic preserved ("start now"), implementation
  switches from `ctx.runtime.run(...)` (synchronous) to enqueue.
- New `start_now="synchronous"` value or a separate
  `synchronous_assign_task` tool preserved as the legacy path for tests
  and any caller that depends on the blocking shape.
- Feature flag `background_delegation_enabled` defaulting to false
  until the CIN is approved + tests ship.

**Stop point.** No code; produce
`docs/CHANGE_IMPACT_NOTICES/background-delegation-execution.md` and
wait.

---

## Phase 2G — Worker session isolation (**NEEDS CIN**, depends on 2F)

**Goal.** Delegated tasks run in isolated worker sessions cloned from
the parent at delegation time. Uses the `task_session_id` column
already added in 2A.

**Why CIN.** Existing delegation shares the parent session; isolating
the child changes how memory and context flow during delegation, which
is a behavioral change to `managed_agent_delegate` /
`managed_agent_assign_task`.

**Outline of what the CIN will propose:**
- Session manager clones the parent session at delegation, writing the
  new `session_id` to `agent_tasks.task_session_id`.
- New `EventType.AGENT_SESSION_FORKED / AGENT_SESSION_MERGED`.
- On task completion, summary is rolled into the parent session via the
  return path; full transcript stays in the child session for audit.
- Feature flag `worker_session_isolation_enabled`.

**Stop point.** No code; produce
`docs/CHANGE_IMPACT_NOTICES/worker-session-isolation.md` and wait.

---

## Cross-cutting expectations

- **Every phase ships with the tests listed in its section.** The 12
  test gaps from the preservation matrix are distributed across 2A–2D
  and must all close by end of 2D.
- **Every phase updates docs in the same PR.** Specifically:
  - 2A → `docs/architecture/overview.md` (event types), and the manager
    schema doc.
  - 2B → `docs/user-guide/agents.md` for the new Capability Inspector;
    screenshots required (per CONTRIBUTING.md).
  - 2C → `docs/architecture/overview.md` event table.
  - 2D → new `docs/user-guide/approvals.md`.
  - 2E–2G → covered by their CINs.
- **No phase silently changes anything in `docs/AUGMENTED_FEATURES.md`.**
- **No phase touches `src/openjarvis/core/registry.py` ABC contracts,
  `BaseAgent` / `ToolUsingAgent`, `InferenceEngine`, `MemoryBackend`,
  or `EventBus` core.** Those are foundation contracts.

## Open design questions to resolve before 2B starts

1. **Datasource binding model.** The proposal puts `data_sources` as a
   first-class array on the agent record. Today the project has
   `channel_bindings` (per-agent, for messaging only) and global
   `connectors/` (data ingest, not per-agent). Three options:
   - (a) Add a parallel `agent_data_source_bindings` table mirroring
     `channel_bindings`. Additive. Recommended.
   - (b) Promote `connectors/` to a per-agent-bound model. Breaking;
     needs a CIN.
   - (c) Defer datasource binding; ship 2B with skills-only Inspector
     and add datasources in 2B.5 after deciding.
2. **`preset` semantics.** The proposal treats preset as a live link
   that auto-populates skills/datasources when changed. Today the
   `template_id` is a one-shot scaffold. Three options:
   - (a) Surface presets in the Inspector as one-shot "apply" buttons,
     consistent with today's semantics. Additive.
   - (b) Promote `template_id` to a live binding (preset changes
     re-derive skills). Breaking; needs a CIN.
   - (c) Defer.
3. **Capability inheritance source.** Manager-imposed inheritance is the
   axis declared in 2A but not populated until a policy source exists.
   Three options:
   - (a) Inherit from the manager's `effective_*` minus their `blocked_*`.
     Simple; lands in 2B.
   - (b) Introduce an explicit `manager_policy_json` blob on
     `managed_agents` that the manager edits. More expressive; small
     additive schema change.
   - (c) Defer inheritance population to a later phase.
4. **User identity for `created_by` / `updated_by`.** Project has no
   user-identity model today. Three options:
   - (a) Capture the chat/session id as `created_by` in the
     `agent_config_versions` row. Coarse but works today.
   - (b) Defer until the project ships a real user model.
   - (c) Capture nothing.

I have a recommendation for each (1a / 2a / 3a / 4a) but each is a
judgment call. **Phase 2B is fully unblocked under those defaults**, but
if you'd prefer different choices, picking them now avoids rework.

## Status of phases

| Phase | Status | Needs approval before code? |
|---|---|---|
| 2A — Foundational additions | **Shipped 2026-05-22** | No (purely additive) |
| 2B — Capability Inspector + UI | **Shipped 2026-05-22** (backend); frontend not independently regression-tested in a browser | No (purely additive) |
| 2C — Task lifecycle event emission | **Shipped 2026-05-22** | No (purely additive) |
| 2D — Approval flow (data plane + tool-dispatch enforcement) | **Shipped 2026-05-22** (data plane); **tool-dispatch enforcement shipped 2026-05-22** in `2f2d0c75` under CIN `approval-enforcement-at-tool-dispatch.md` | No (data plane); Yes — done (enforcement) |
| 2E — Chief as canonical ingress | **Shipped 2026-05-22** under CIN `chief-as-canonical-ingress.md` (flag live) | Yes — done |
| 2F — Background delegation | **Shipped 2026-05-22** in `2f2d0c75` (+`d69e6f1e` test hooks) under CIN `background-delegation-execution.md` | Yes — done |
| 2G — Worker session isolation | **Shipped 2026-05-23** in `1d13e8a2` (+`d69e6f1e` test hooks) under CIN `worker-session-isolation.md` | Yes — done |

### Post-Phase-2 follow-ups

- **Addendum (Agent Assigned Jobs)** — CIN `agent-assigned-jobs.md` approved 2026-05-23; implementation landed in `db412a93` (2026-05-26). See the addendum in `docs/HIERARCHICAL_AGENT_IMPLEMENTATION_PLAN.md`.
- **Known test issues at the time of this update:**
  - One flake under random pytest order: `tests/server/test_phase2g_worker_session_isolation.py::test_two_concurrent_background_delegations_do_not_interleave`. Passes deterministically; flakes when preceded by `test_agent_manager_routes.py::TestResolveToolSpecs._registered_tools` fixture (importlib.reload chain corrupts mid-test module state). Functional behavior is sound — see end-to-end smoke. Root cause not yet pinned.
  - `tests/security/test_capabilities.py` + `test_guardrails.py` fail on hosts where the `openjarvis_rust` extension is not built (mandatory per `_rust_bridge.py`). Build with `uv pip install -e rust/crates/openjarvis-python` after installing a Rust toolchain.
  - 2 pre-existing `:memory:` SQLite path failures in `test_channel_bridge_deep_research.py`.

## Estimated sequencing (calendar-loose)

- 2A: 2–3 days of focused work.
- 2B: 5–8 days (UI plus modal plus history drawer plus tests).
- 2C: 1–2 days.
- 2D: 3–5 days.
- 2E / 2F / 2G: each is 3–5 days *after* its CIN is approved; CINs
  themselves are produced in 1 day each.

These are estimates, not promises.
