# Augmented Features Inventory

> **Status:** Phase 1 audit artifact, generated 2026-05-20.
> **Purpose:** Canonical list of project-specific features that extend the
> OpenJarvis foundation and **must not be removed, merged away, or
> functionally degraded** without an approved Change Impact Notice under
> `docs/CHANGE_IMPACT_NOTICES/<slug>.md`.

---

## How to read this file

- **PROTECTED** is the default status. Every feature listed here is
  protected.
- A feature is only removed from PROTECTED status when the user explicitly
  approves a Change Impact Notice that deprecates it.
- The "Location" column points to the canonical implementation, not every
  file that references it.
- "Why protected" is a short sentence about user-visible value — what
  breaks for the user if this feature disappears.
- A Phase 2 plan that touches any line in this file must produce a
  Change Impact Notice listing exactly which feature it changes, why, and
  what compatibility shim it provides.

---

## 1. Chain-of-command primitives (already present, beyond vanilla OpenJarvis)

| Feature | Location | Why protected | Status |
|---|---|---|---|
| Chief action envelope (`OrchestratorAction` with `COMPLETE`, `DELEGATE`, `EXECUTE_DIRECT`, `ASK_USER`, `FAIL`) | `src/openjarvis/agents/chief.py:1-34` | Structured Chief-mode decision shape that Phase 2 will build on. | **PROTECTED** |
| OrchestratorAgent "chief" mode | `src/openjarvis/agents/orchestrator.py:97` (`if self._mode == "chief": return self._run_chief(...)`) | The Chief is already implemented as a mode of the orchestrator. | **PROTECTED** |
| Hierarchy storage with cycle prevention | `src/openjarvis/agents/manager.py:17-29` (schema) + `_validate_manager_assignment` | Stops users from creating loops in the org chart. | **PROTECTED** |
| `managed_agent_delegate` tool (synchronous reply with optional `tools_allowed` least-privilege) | `src/openjarvis/tools/managed_agent_tools.py:263-377` | The current path for one agent to ask another for help. | **PROTECTED** |
| `managed_agent_assign_task` tool (durable task creation, optional start) | `src/openjarvis/tools/managed_agent_tools.py:418-560` | Durable delegation primitive — Phase 2's queue/background work builds on this. | **PROTECTED** |
| `managed_agent_directory` tool | `src/openjarvis/tools/managed_agent_tools.py:200-260` | Discovery of available agents for delegation. | **PROTECTED** |
| `agent_tasks` table + `assigned_by_agent_id` | `src/openjarvis/agents/manager.py:32-42` | Existing task ledger; Phase 2 will extend it additively. | **PROTECTED** |
| Chief Pending Card (mid-turn input requests) | `frontend/src/pages/AgentsPage.tsx:2293` (`ChiefPendingCard`), backed by `fetchChiefPending(agent.id)` | Existing UX for "agent paused waiting for a human answer". | **PROTECTED** |
| Per-agent personality field (`config.personality`) | `src/openjarvis/server/managed_agent_runtime.py:276` + `AgentPersonalitySection` (`frontend/src/pages/AgentsPage.tsx`) | Added in the immediately-prior turn; voice/tone shaping of agent replies. | **PROTECTED** |
| Chief-as-canonical-ingress: `POST /v1/chief/messages`, `GET /v1/chief`, `GET /v1/chief/status`, `POST /v1/chief/designate` | `src/openjarvis/server/agent_manager_routes.py` (`chief_router`) | Phase 2E. The canonical user-facing ingress; routes chat + interact traffic through the Chief. | **PROTECTED** |
| `is_chief` designation + `get/set_chief_agent`, back-fill | `src/openjarvis/agents/manager.py` | Phase 2E. Single-row Chief flag with atomic re-designation. | **PROTECTED** |
| `chief_ingress.enabled` config flag | `src/openjarvis/core/config.py` (`ChiefIngressConfig`) | Phase 2E. Opt-out switch for Chief ingress (default true). | **PROTECTED** |
| Canonical `TaskStatus` enum + legacy mapper | `src/openjarvis/core/types.py` | Phase 2A. 11-state task lifecycle vocabulary. | **PROTECTED** |
| `agent_tasks` canonical columns (`parent_task_id`, `root_task_id`, `requires_approval`, …) | `src/openjarvis/agents/manager.py` | Phase 2A. Additive durable task model. | **PROTECTED** |
| `task.*` lifecycle events | `src/openjarvis/core/events.py` + emitters in `manager.py` | Phase 2C. First-class task signals on the bus + activity sidebar. | **PROTECTED** |
| Config version history (`agent_config_versions`) + revert | `src/openjarvis/agents/manager.py`, `GET /versions` + `POST /revert` routes | Phase 2A/2B. Append-only audit trail with non-destructive revert. | **PROTECTED** |
| Capability axes (`inherited/blocked/requires_approval`) + `/preview` endpoint | `src/openjarvis/agents/capabilities.py`, `POST /v1/managed-agents/{id}/preview` | Phase 2A. Six-axis capability resolution. | **PROTECTED** |
| Capability Inspector UI | `frontend/src/pages/AgentsPage.tsx` (`CapabilityInspector`) | Phase 2B. Axis-badged capability view + preview modal + history drawer. | **PROTECTED** |
| Approval flow (`ApprovalStore`, `agent_approvals`, `/v1/approvals`) | `src/openjarvis/agents/approvals.py` + `approvals_router` | Phase 2D. Approval request/grant/deny with immutable decisions. | **PROTECTED** |
| Approval gating at tool dispatch (`_approval_gate`, single-use args-scoped grants, Option B auto-resume) | `src/openjarvis/server/managed_agent_runtime.py` (`_approval_gate`, `_block_pending_approval`) + `agent_manager_routes.py` (`_redispatch_after_grant`) | Phase 2D enforcement. Connects the `requires_approval_tools` axis to the approval store so gated tools block on human sign-off. Gated by `[approval_gating] enabled` (default off). | **PROTECTED** |
| Background delegation execution (`BackgroundDelegationExecutor`, bounded pool, Option B parent notification) | `src/openjarvis/server/background_delegation.py` + enqueue branch in `src/openjarvis/tools/managed_agent_tools.py` (`ManagedAgentAssignTaskTool`) | Phase 2F. `managed_agent_assign_task(start_now=True)` enqueues the kickoff on a bounded worker pool instead of blocking the delegating agent; completion posts a delegated-mode message back to the parent's log. Gated by `[background_delegation] enabled` (default off; flag-off path is byte-identical). | **PROTECTED** |
| Worker session isolation (per-task `session_id` on `agent_messages`, scoped history loader, `AGENT_SESSION_FORKED` / `AGENT_SESSION_MERGED`) | `src/openjarvis/agents/manager.py` (schema + `_worker_session_isolation_enabled` + session-aware helpers) + `src/openjarvis/server/managed_agent_runtime.py` (`_active_task_session_id` contextvar, `task_session_id` param on `run()`) + `src/openjarvis/server/background_delegation.py` (executor + merge event) + `src/openjarvis/tools/managed_agent_tools.py` (`_mint_worker_session_id`, `_emit_session_forked`) | Phase 2G. Delegated turns run against a per-task slice of the worker's message log; parallel-safe; reuses the 2F parent notification as the merge. Audit-facing routes pass `include_all_sessions=True`. Gated by `[worker_session_isolation] enabled` (default off; flag-off path is byte-identical). | **PROTECTED** |

## 2. Live observability surfaces (augmented beyond OpenJarvis defaults)

| Feature | Location | Why protected | Status |
|---|---|---|---|
| `/v1/agents/events` WebSocket fan-out of agent runtime events | server side: managed agent runtime emits; frontend: `frontend/src/lib/useAgentEvents.ts:10-111` | The transport powering the live activity sidebar and org-chart pulse. | **PROTECTED** |
| `InterAgentActivityPanel` right-side sidebar | `frontend/src/pages/AgentsPage.tsx:3814` (filters: `all`/`active`/`alerts`/`direct`, polled history merged with live events) | This is the operational conversation log; `AGENTS.md` § "UI rules" relies on it. | **PROTECTED** |
| `AgentOrgChart` with live activity pulse | `frontend/src/pages/AgentsPage.tsx:3594`, `connectorStyle()` line ~137 | Hierarchy + activity visualized together; canonical org view. | **PROTECTED** |
| SSE chat-token streaming bridge | `src/openjarvis/server/stream_bridge.py:1-368` (events: `agent_turn_start`, `inference_start/end`, `tool_call_start/end`) | OpenAI-compatible streaming surface; third-party clients depend on it. | **PROTECTED** |
| Trace store (append-only SQLite, WAL, FTS, `parent_trace_id`, `run_id`) | `src/openjarvis/traces/store.py:81-250` | Foundation primitive but augmented with FTS UI surfacing. | **PROTECTED** |
| `LogsTab` and trace debugger UI | `frontend/src/pages/AgentsPage.tsx` "logs" tab + `frontend/src/components/Dashboard/TraceDebugger.tsx` | User-visible trace navigation. | **PROTECTED** |
| Energy / power telemetry | `src/openjarvis/telemetry/energy_monitor.py` + vendor backends (`energy_nvidia.py`, `energy_amd.py`, `energy_apple.py`, `energy_raml.py`) | "Dollars saved vs cloud" + energy stat panel on Overview tab. | **PROTECTED** |
| Per-agent telemetry rollup (Overview "Agent Statistics" + "Local Utilization" + "Dollars Saved vs.") | `frontend/src/pages/AgentsPage.tsx:6519-6593` | Headline savings narrative for the user; non-trivial UX. | **PROTECTED** |

## 3. Agent detail tabs

The agent detail view has eight tabs. Each is protected.

| Tab | Component / line | Why protected |
|---|---|---|
| `overview` | `AgentsPage.tsx:6517` (renders `AgentInstructionSection`, `AgentPersonalitySection`, `AgentConfigGrid`, `AgentOrganizationSection`, `AgentPresetToolsSection`, savings panel, channels summary) | Primary configuration surface. |
| `interact` | `InteractTab` at `AgentsPage.tsx:4209`, `sendAgentMessage` → `/v1/managed-agents/{id}/messages` | Direct-to-agent chat. Phase 2 plans to *route through Chief by default* but the InteractTab itself must remain. |
| `channels` | `ChannelsTab` (bound channels: Slack/Telegram/etc.) | Per-agent channel binding management. |
| `messaging` | `MessagingTab` (per-agent message history) | Inter-agent message log. |
| `tasks` | Agent task ledger view with status + project filter (`AgentsPage.tsx:6628`) | Operational task list. |
| `memory` | Summary memory display | Surfaces compressed agent state. |
| `learning` | `LearningTab` | Distillation/learning history. |
| `logs` | `LogsTab` | Per-agent trace navigation. |

## 4. Capability / catalog system

| Feature | Location | Why protected | Status |
|---|---|---|---|
| `enrich_agent_record` adding `configured_tools`, `configured_skills`, `effective_skills`, `auto_tools`, `effective_tools`, `knowledge_enabled` | `src/openjarvis/agents/capabilities.py:128-142` | API shape that the frontend reads. | **PROTECTED** |
| `effective_agent_tool_names` (auto-injects collaboration tools always, project tools for managers, knowledge tools for `deep_research`) | `src/openjarvis/agents/capabilities.py:105-125` | Removing this silently downgrades agent behavior. | **PROTECTED** |
| `build_agent_tool_instances` with `restrict_to_tool_names` (least-privilege per delegation) | `src/openjarvis/agents/capabilities.py:212-346` | The mechanism that makes `tools_allowed=` actually constrain a subordinate. | **PROTECTED** |
| Template library (`.toml` per template, builtin + user dirs) | `src/openjarvis/agents/library.py:31-149` + `src/openjarvis/agents/templates/*.toml` | Preset catalog the launch wizard reads. | **PROTECTED** |
| Skill registry + skill-as-tool adapter | `src/openjarvis/skills/`, `src/openjarvis/skills/tool_adapter.py` | Wires the entire skill ecosystem (Hermes/OpenClaw skill imports). | **PROTECTED** |
| `AgentPresetToolsSection` capability editor | `frontend/src/pages/AgentsPage.tsx:2565` | The UI that lets users assign skills/presets/tools. Phase 2 will *extend* its badge vocabulary, not replace it. | **PROTECTED** |

## 5. Channels (augmented surface beyond vanilla OpenJarvis)

`channel_bindings(agent_id, channel_type, config_json, session_id, routing_mode)` in `agents/manager.py:45-53` is the binding table. The connector implementations themselves live in `src/openjarvis/channels/`.

| Channel | Implementation | Status |
|---|---|---|
| WhatsApp (Baileys bridge, bundled Node.js) | `src/openjarvis/channels/whatsapp_baileys.py` + `whatsapp_baileys_bridge/` | **PROTECTED** |
| Telegram | `src/openjarvis/channels/` (`channel-telegram` extra) | **PROTECTED** |
| Discord, Slack, Line, Viber, Messenger, Reddit, Mastodon, XMPP, RocketChat, Zulip, Twitter, Twitch, Nostr, Twilio, Email (Gmail) | per-channel modules in `src/openjarvis/channels/`, optional extras in `pyproject.toml:91-110` | **PROTECTED** |

## 6. Connectors / data sources (augmented surface)

`src/openjarvis/connectors/` contains 30+ connector implementations. Each is protected:

- Gmail, Google Drive, Google Calendar, Google Tasks (OAuth flows in `connectors/oauth.py`)
- News RSS (`connectors/news_rss.py`)
- Web search via DuckDuckGo / Tavily / Brave
- Notion, Linear, GitHub, Confluence, etc. (per the connector list)
- File-system / PDF / document ingestion

Frontend home: `frontend/src/pages/DataSourcesPage.tsx`.
**Status:** PROTECTED.

## 7. Projects + Mission Control (substantially augmented)

| Feature | Location | Why protected | Status |
|---|---|---|---|
| Projects store with categories, milestones, statuses | `src/openjarvis/projects/store.py` | Headline organizational surface. | **PROTECTED** |
| Project / task tools | `src/openjarvis/tools/project_tools.py` (`project_create`, `project_create_task`, …) | Used directly by Chief/manager prompts in `managed_agent_runtime.py`. | **PROTECTED** |
| Mission Control fetcher + UI | `frontend/src/components/MissionControl/` + `frontend/src/lib/api.ts:fetchMissionControl` | Project hierarchy + task ownership view. | **PROTECTED** |
| `ProjectsPage`, `ProjectDashboardPage`, `ProjectDetailPage`, `ProjectTimelinePage` | `frontend/src/pages/` | Routes users depend on. | **PROTECTED** |
| Project-task ↔ agent-task linkage | `agent_tasks.project_task_id` + `project_id` migration in `manager.py` | Anchor between Mission Control and agent ledger. | **PROTECTED** |
| `project-status-report` skill | recent commit `e67d541b` | User-facing report skill. | **PROTECTED** |
| Default "Unassigned Work" project routing for ad-hoc chat-created tasks | `managed_agent_runtime.py` | Prevents floating tasks. | **PROTECTED** |

## 8. Voice (speech in + speech out)

| Feature | Location | Status |
|---|---|---|
| WebSocket speech-stream endpoint `/v1/speech/stream` | server side; frontend hook `frontend/src/hooks/useStreamingSpeech.ts` | **PROTECTED** |
| Multi-backend TTS discovery (Cartesia, OpenAI, Kokoro local) | `src/openjarvis/speech/_tts_discovery.py`, `cartesia_tts.py`, `openai_tts.py`, kokoro extra (`pyproject.toml:135-140`) | **PROTECTED** |
| TTS player hook | `frontend/src/hooks/useTTSPlayer.ts` | **PROTECTED** |
| Faster-Whisper STT (`speech` extra) + Silero VAD + Deepgram option | `pyproject.toml:120-125` | **PROTECTED** |
| F5-TTS voice cloning extra | `pyproject.toml:122` | **PROTECTED** |

## 9. Desktop wrapper

| Feature | Location | Status |
|---|---|---|
| Tauri desktop shell with plugins (autostart, global-shortcut, notification, process, shell, updater) | `frontend/src-tauri/` + `frontend/package.json` deps | **PROTECTED** |
| Setup wizard / onboarding | `frontend/src/components/setup/`, `SetupScreen.tsx`, `GetStartedPage.tsx` | **PROTECTED** |
| Command palette | `frontend/src/components/CommandPalette.tsx` | **PROTECTED** |
| System pulse widget | `frontend/src/components/SystemPulse.tsx` | **PROTECTED** |
| OptIn modal (telemetry/anonymous savings opt-in) | `frontend/src/components/OptInModal.tsx` | **PROTECTED** |

## 10. Engines / inference (foundation but pluggable extras)

Foundation contracts in `src/openjarvis/engine/` are **not in scope** for
this protection inventory — they're OpenJarvis foundation. The augmented
piece worth calling out:

| Feature | Location | Status |
|---|---|---|
| Mining / Pearl on-device inference acceleration | `src/openjarvis/mining/`, `mining-pearl-cpu` + `mining-pearl-vllm` extras | **PROTECTED** |
| Engine fallback chain w/ availability dot in UI | `frontend/src/pages/AgentsPage.tsx:2150-2210` (Ollama HTTP probe + status dot) | **PROTECTED** |

## 11. Learning + distillation

| Feature | Location | Status |
|---|---|---|
| `TraceDrivenPolicy` router | `src/openjarvis/learning/trace_policy.py` | **PROTECTED** |
| Distillation / frontier-driven harness learning | `src/openjarvis/learning/distillation/` | **PROTECTED** |
| Per-agent learning enable flag + `LearningTab` | `managed_agents.learning_enabled` + `LearningTab` in `AgentsPage.tsx` | **PROTECTED** |
| `agent_learning_log` table | `src/openjarvis/agents/manager.py:79-88` | **PROTECTED** |

## 12. Scheduler

| Feature | Location | Status |
|---|---|---|
| Cron / interval / once scheduler with SQLite persistence | `src/openjarvis/scheduler/scheduler.py`, `scheduler/store.py` | **PROTECTED** |
| MCP scheduler tools (`schedule_task`, `list`, `pause`, `resume`, `cancel`) | `src/openjarvis/scheduler/tools.py` | **PROTECTED** |

## 13. Sandbox + security

| Feature | Location | Status |
|---|---|---|
| `SandboxedAgent` Docker/Podman wrapper | `src/openjarvis/sandbox/runner.py` | **PROTECTED** |
| Mount allowlist | `src/openjarvis/sandbox/mount_security.py` | **PROTECTED** |
| Secret + PII scanners | `src/openjarvis/security/scanner.py` | **PROTECTED** |
| GuardrailsEngine wrapping `InferenceEngine` | `src/openjarvis/security/guardrails.py` | **PROTECTED** |
| Subprocess sandbox + taint tracking | `src/openjarvis/security/subprocess_sandbox.py`, `security/taint.py` | **PROTECTED** |
| Audit log (SQLite security events) | `src/openjarvis/security/audit.py` | **PROTECTED** |

## 14. Sessions

| Feature | Location | Status |
|---|---|---|
| `SessionStore` (cross-channel user identity, SQLite) | `src/openjarvis/sessions/session.py` | **PROTECTED** |
| `SessionIdentity` mapping user_id → channel identifiers | `sessions/session.py:26-28` | **PROTECTED** |

## 15. Other surfaces worth calling out

| Feature | Location | Status |
|---|---|---|
| `start.bat` / `stop.bat` / `Start_Claude_AI.bat` first-run system setup | repo root | **PROTECTED** (per the standing rule: first-run setup belongs in `start.bat`, not manual commands) |
| WSL backend topology with port-8000 wslrelay | per WSL memory | **PROTECTED** |
| Ollama model store on ext4 VHD under F:\ (with `use_mmap=false`) | recent commit `b7017d21` | **PROTECTED** |
| `prompt_registry` (modular orchestrator prompts) | `src/openjarvis/learning/intelligence/orchestrator/prompt_registry.py` | **PROTECTED** |

---

## 16. Excluded from this inventory (intentionally)

These are part of the OpenJarvis foundation contract and are governed by
the upstream docs (`docs/architecture/`), not this file:

- `BaseAgent` / `ToolUsingAgent` ABCs
- `InferenceEngine` ABC
- `MemoryBackend` ABC + the five built-in backends
- The decorator-based `RegistryBase[T]` and all typed registries
- `EventBus` core (the bus itself; specific event *types* added in this
  project are listed above under §2)

Any change to those contracts is a foundation change and requires a
Change Impact Notice on its own merits.

---

## 17. Notice / approval workflow reminder

Any Phase 2 (or later) work that proposes to:

- remove a row from this file,
- change a column described above (schema or API),
- change an API contract,
- change persistence shape,
- change user workflows,
- disable current behavior,
- replace a subsystem,

must produce `docs/CHANGE_IMPACT_NOTICES/<slug>.md` and **stop for explicit
approval** before implementation. See `AGENTS.md` § "Change-control
protocol".
# Agent Assigned Jobs

Status: Protected augmented feature

Jarvis supports per-agent assigned jobs managed from each agent's Overview surface.
Jobs are durable agent capabilities, not transient UI state. Supported first-pass
job types are `cron`, `interval`, `once`, `manual`, and app-event-driven
`if_this_then_that` jobs. Cron expressions are stored as cron strings in the
agents database; the UI converts computed next-run timestamps to the user's
browser timezone for display.

Protected behavior:
- jobs remain assigned to managed agents,
- job definitions and job runs are persisted in the agents database,
- job firing creates tracked agent work and records job run history,
- designated Chief attribution is preserved when a job materializes work,
- delegation policy is stored with the job and copied into task progress,
- job capabilities are exposed through the Capability Inspector axes,
- IFTTT jobs trigger from built-in or registered app events without polling,
- existing per-agent `schedule_type` / `schedule_value` config remains supported.

# Personal Life Manager Agent Templates

Status: Protected augmented feature

Jarvis includes built-in Personal Life Manager templates that can be instantiated
from the agent template catalog without changing the Chief Orchestrator ingress
or protected task/job ledgers.

Protected templates:
- `life_manager`
- `sermon_study`
- `health_routine`
- `finance_reminder`
- `learning_coach`

Protected behavior:
- templates stay additive to the existing template library,
- instantiated agents remain governed by Chief routing and capability policy,
- routines and reminders use protected Agent Jobs and task ledgers rather than
  mutable UI-only state,
- health and finance templates do not provide professional medical, legal, tax,
  investment, or financial advice,
- templates do not instruct agents to expose hidden chain-of-thought.

# Personal Planning Dashboard

Status: Protected augmented feature

Jarvis includes an additive Personal Planning Dashboard at `/life-planner`.
It derives personal planning views from existing Mission Control project tasks,
managed agents, and per-agent jobs.

Protected behavior:
- the dashboard remains a derived view over durable tasks and jobs,
- life-domain and horizon filters do not replace canonical project/task/job
  persistence,
- completing a planning item updates the durable project task or agent job
  status and then removes completed work from the derived planning queue,
- existing Mission Control, Agents, Projects, and Jobs routes remain unchanged,
- no hidden chain-of-thought is displayed in dashboard rows or summaries.
