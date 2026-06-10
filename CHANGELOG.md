# Changelog

All notable changes to OpenJarvis are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

---

## [Unreleased]

### Added

- **Interactive hands-free voice conversation (desktop)** — a headset toggle in
  the chat composer starts a continuous, interruptible voice loop
  (Listening -> speech-to-text -> LLM -> spoken reply -> Listening). Full
  barge-in: speaking over the assistant immediately stops playback, cancels the
  in-flight TTS *and* LLM stream, and returns to listening, with the cut-off
  turn saved and flagged `interrupted`. Driven by an explicit, unit-tested
  conversation state machine; configurable silence timeout, minimum speech
  duration, allow-interruption (full vs half duplex), and mic/speaker device
  under Settings -> Speech -> Hands-free conversation. Additive and reuses the
  existing streaming STT/TTS and chat send path (Chief Orchestrator ingress
  unchanged); the prior wake-word, manual-mic, and text paths are preserved.
- **Proactive Watchtower announcements (desktop)** — on login the desktop
  client greets you by voice + toast ("Jarvis online. Monitoring active."), and
  while open it speaks and toasts every new Watchtower finding as it appears
  (backlog is baselined as already-seen, so login is greeting-only). Voice uses
  the existing client-side TTS, respects the Watchtower speech toggle and
  Do-Not-Disturb quiet hours, and is gated behind one user gesture for browser
  autoplay. Purely additive frontend change (the prior actionable-only toast
  behavior is now a subset); no backend changes.

- **Controlled Autonomy (Rollback + Audit)** — a `RollbackStore` that records
  reversible autonomous actions with an undo payload and reverts them via a
  handler registry (built-in `file_write` restores prior bytes / deletes
  newly-created files; irreversible types like email/deploy get a
  compensating-note and are never auto-undone; handler failure is captured),
  plus an Event-Log audit-report builder, agent tools (`rollback_record`,
  `rollback_list`, `rollback_revert`, `audit_report`), and `/v1/rollback*` +
  `/v1/audit/report` REST endpoints. Additive; opt-out via
  `[autonomy].enabled=false`. Does not change the scheduler or approval-gating
  paths.
- **Agent Org Expansion** — a default agent hierarchy (Chief Orchestrator →
  Executive Assistant / Workflow Manager / CTO / Knowledge Manager / Life
  Manager → specialists) via 15 new role templates, an optional `org_role`
  field on templates (used as the default org placement at create time), and
  an idempotent `bootstrap_default_org` exposed as `POST /v1/org/bootstrap` +
  `GET /v1/org` and a `jarvis org` CLI (`bootstrap` / `show`). Additive and
  opt-in; reuses the existing org model; the Chief remains the sole
  human-facing ingress.
- **Life Manager** — a durable backend for life domains and recurring routines
  with due-tracking (daily/weekly/monthly/custom cadence advancing from
  completion time, streaks, a "what's due today" query), agent tools
  (`life_add_domain`, `life_add_routine`, `life_complete_routine`, `life_due`,
  `life_list`), and read/write `/v1/life` REST endpoints. Additive; opt-out via
  `[lifemanager].enabled = false`. Existing life agent templates are unchanged.
- **Task–Code Linkage** — records file changes (FileEvent) and commits
  (CodeChangeLink) linked to tasks/agents/projects via an active-task
  `WorkContext`, with agent tools (`codelink_*`), a Git→task recorder, an
  optional `watchdog`-based file-watcher (off by default), and read-only
  `/v1/codelink` endpoints. Additive; opt-out via `[codelink].enabled=false`;
  watcher opt-in via `[codelink].watch_enabled=true`.
- **Approval Center** — a generalized action-approval queue
  (`ActionApprovalStore`) for arbitrary action types (code/file/email/plan/
  deploy) with an Approve/Reject/Modify/Defer/Ask/Reopen lifecycle, an
  append-only transition trail, a `[action_approvals]` config section, and
  read/write `/v1/action-approvals` REST endpoints. Distinct from and additive
  to the existing tool-gating approvals; opt-out via
  `[action_approvals].enabled = false`.
- **Persisted Event Log** — a durable, queryable SQLite store behind the
  in-memory `EventBus` that persists every event (minus a configurable
  denylist) with indexed correlation IDs (`agent_id`, `task_id`,
  `project_id`, `run_id`) and the full JSON payload. New `[eventlog]` config
  section and read-only `GET /v1/events` + `GET /v1/events/feed` endpoints.
  Foundation for the Autonomous Workflow Engine (Approval Center, Task–Code
  Linkage, audit, activity feed). Additive; opt-out via
  `[eventlog].enabled = false`.
- **Chief Orchestrator as canonical ingress** — chat-page and
  agent-interact traffic now routes through the designated Chief
  Orchestrator, which decides whether to answer directly, delegate to a
  subordinate, or decompose the work. New `POST /v1/chief/messages`
  endpoint plus `GET /v1/chief`, `GET /v1/chief/status`, and
  `POST /v1/chief/designate`. A single agent carries an `is_chief` flag
  (`managed_agents.is_chief`); fresh installs auto-promote the first
  agent whose org-role matches the chief heuristic. The OpenAI-compatible
  `/v1/chat/completions` and direct `/v1/managed-agents/{id}/messages`
  surfaces are unchanged — the chat input shows a "Direct mode" toggle,
  the agent-interact tab a "Route through Chief" toggle, and the org
  chart a Chief badge. Gated by `[chief_ingress] enabled` (default true;
  set false to opt out). See
  `docs/CHANGE_IMPACT_NOTICES/chief-as-canonical-ingress.md`.
- **Capability Inspector** — the agent Overview tab gains a six-axis
  capability view (assigned / inherited / blocked / approval-gated /
  effective) backed by new `enrich_agent_record` fields, a
  "Preview Capabilities" modal (`POST /v1/managed-agents/{id}/preview`),
  and an append-only config version history with non-destructive revert
  (`GET /v1/managed-agents/{id}/versions`,
  `POST /v1/managed-agents/{id}/revert`).
- **Durable task model + lifecycle events** — `agent_tasks` gains
  canonical fields (`parent_task_id`, `root_task_id`, `request_source`,
  `requesting_user`, `priority`, `requires_approval`, …, all nullable
  and additive). New `task.*` events (`created`/`updated`/`delegated`/
  `completed`/`failed`) emit on the event bus and stream to the activity
  sidebar. A canonical 11-state `TaskStatus` enum maps to/from the
  legacy four-state vocabulary at the persistence boundary.
- **Approval flow** — new `ApprovalStore` + `agent_approvals` table and
  `GET/POST /v1/approvals` endpoints with `approval.requested` /
  `approval.resolved` events. Decisions are immutable once made.
- **Approval gating (tool-dispatch enforcement)** — a managed agent now
  pauses for human sign-off before running a tool listed in its
  `requires_approval_tools` capability axis. The dispatch gate consults
  the approval store per `(agent, capability, arguments)` triple: a
  pending request blocks the call and moves the owning task to
  `awaiting_approval`; a grant is single-use and argument-scoped; a
  denial returns the reason to the agent. Granting re-dispatches the
  blocked agent automatically (no need to re-send the message). Pending
  approvals surface in the Inter-Agent Activity sidebar and an agent
  Overview card with Grant/Deny actions. Gated by `[approval_gating]
  enabled` (**default false** — an opt-in security posture; turning it
  on changes whether a tool runs). Direct CLI/SDK tool use is out of
  scope and ungated. See `docs/user-guide/approvals.md` and
  `docs/CHANGE_IMPACT_NOTICES/approval-enforcement-at-tool-dispatch.md`.
- **Background delegation execution** —
  `managed_agent_assign_task(start_now=True)` can now enqueue the
  subordinate's kickoff turn on a bounded worker pool instead of
  running it inline on the delegating agent's thread, so a Chief can
  fan work out to several subordinates in parallel. The existing
  loop/depth guards are evaluated before enqueue. When a background
  turn finishes the executor posts a short completion (or failure)
  message to the **parent agent's** message log so the upward return
  path is honored; the parent picks it up on its next turn (no
  re-dispatch). In-memory job queue — a server crash leaves the
  owning task in `delegated` / `in_progress` and re-runnable. Gated
  by `[background_delegation] enabled` (**default false** — changes
  an existing tool's observable behavior, so opt-in). With the flag
  off the synchronous path is byte-identical. See
  `docs/user-guide/agents.md` → "Background delegation" and
  `docs/CHANGE_IMPACT_NOTICES/background-delegation-execution.md`.
- **Worker session isolation** — each delegated task can now run
  against its own scoped session inside the worker's message log, so
  the subordinate sees only its per-task slice instead of the worker's
  full history. At delegation time a fresh `session_id` is minted and
  written to `agent_tasks.task_session_id`; the runtime threads it
  through the subordinate's writes and history reads. The Phase 2F
  parent notification doubles as the merge. New schema column
  `agent_messages.session_id` (nullable, additive) and new event
  types `AGENT_SESSION_FORKED` / `AGENT_SESSION_MERGED`. Two
  concurrent background delegations against the same worker no longer
  interleave their context. Audit-facing routes pass
  `include_all_sessions=True` so the UI's full view is preserved.
  Gated by `[worker_session_isolation] enabled` (**default false** —
  changes what context flows into delegated turns, so opt-in). With
  the flag off the runtime and message log are byte-identical. See
  `docs/user-guide/agents.md` → "Worker session isolation" and
  `docs/CHANGE_IMPACT_NOTICES/worker-session-isolation.md`.
- **Project Management workspace** — local-first projects with nested
  tasks/subtasks, assignee/status/priority/dates metadata, notes, a
  timeline/Gantt view, a KPI dashboard, and AI summaries. Backed by a
  server-side SQLite store (`~/.openjarvis/projects.db`) exposed via a new
  `/v1/projects` API, a `project_management` data-source connector (so agents
  can query project state), a `project_assistant` agent template, a
  `project-status-report` skill (grounded health/risks/next-actions report),
  and a `project-management` preset
  (`jarvis init --preset project-management`). New sidebar **Projects**
  section with portfolio, detail/task-tree, timeline, and dashboard pages.
- **Mission Control** — the sidebar "Dashboard" is renamed **Mission
  Control** and augmented (engine telemetry retained) with a live view of
  projects, nested tasks/subtasks with progress, and the managed-agent
  roster showing which agents are working/idle and the task each is on.
  Backed by a new aggregate endpoint `GET /v1/projects/mission-control`.
  Managed-agent tasks now link to a project task/subtask
  (`project_task_id`); a running agent auto-updates its linked task
  (notes + status, gated by a 3-tier org-chart role model:
  Project Management / Worker / QA). New `openjarvis.projects.authz`.
- **Library page** in the web/desktop UI (sidebar → Library, `/library`) for
  managing skill and preset definitions (create / edit / delete via a TOML
  editor) and downloading skills from Hermes Agent, OpenClaw, or any GitHub
  repo without the CLI. Backed by new REST endpoints
  `GET /v1/skills/browse` and `POST /v1/skills/install`, which reuse the same
  resolver/importer machinery as `jarvis skill install`. The Capability
  Inspector's previously inert "Library" button now opens this page.
- AI stack support for evaluating other agentic frameworks via subprocess.
  New `evals/backends/external/` subpackage wraps Hermes Agent and OpenClaw
  as one-shot subprocess backends behind the existing `InferenceBackend`
  ABC; new `evals/comparison/` toolkit provides path + commit-pin
  enforcement (`third_party.py`), config templating (`make_configs.py`),
  and LaTeX table generation (`table_gen.py`).
- New optional extra `framework-comparison` (depends on `polars`).
- New pytest marker `live_external` for integration tests requiring real
  foreign-framework installations.

### Changed

- `JarvisAgentBackend.generate_full` and `JarvisDirectBackend.generate_full` now return
  the spec §6.2 extended fields (`energy_joules`, `peak_power_w`, `tool_calls`,
  `turn_count`, `framework`, `framework_commit`, `error`) for cross-framework
  comparison parity. Existing callers that didn't read these fields are unaffected.
- `_third_party.toml` no longer ships user-specific default paths. Set
  `HERMES_AGENT_PATH` and `OPENCLAW_PATH` env vars to point at your local
  checkouts before running the framework-comparison harness; missing or
  empty paths now raise `ThirdPartyNotFoundError` with an actionable hint.
- **Breaking (agents):** managed-agent tasks and runs now require a link to
  a project task/subtask. `AgentManager.create_task(...)` and
  `POST /v1/managed-agents/{id}/tasks` require `project_task_id`;
  `POST /v1/managed-agents/{id}/run` returns 400 if the agent has no
  linked task; the `managed_agent_assign_task` tool gains a required
  `project_task_id`. Existing unlinked agent tasks are auto-migrated to a
  system "Unassigned Work" project (tagged `needs-reconciliation`) so
  agents keep running until reconciled.

#### Skills System (Plans 1, 2A, 2B)

- **Skills core** — every skill is a tool. Skills appear in a system prompt catalog, agents invoke them on demand, content (pipeline results, markdown instructions, or both) gets injected into context.
  - `SkillManifest` + `SkillStep` types with tags, depends, invocation flags, markdown content
  - `SkillManager` — discovery, precedence resolution, catalog XML generation, tool wrapping
  - `SkillTool(BaseTool)` — auto-extracts parameters from step argument templates
  - `SkillExecutor` — sequential pipeline execution with sub-skill delegation
  - Dependency graph with cycle detection, max depth enforcement, capability unions
  - Security: four trust tiers (bundled/indexed/unreviewed/workspace), capability-gated enforcement
  - Skill index module for git-backed registry search

- **agentskills.io spec adoption** — canonical `SKILL.md` format with YAML frontmatter following the [agentskills.io](https://agentskills.io/specification) open standard.
  - `SkillParser` with strict spec validation + tolerant field mapping via `FIELD_MAPPING` table
  - `ToolTranslator` for external tool name translation (Bash -> shell_exec, Read -> file_read, etc.)
  - Source resolvers: `HermesResolver`, `OpenClawResolver`, `GitHubResolver`
  - `SkillImporter` with provenance tracking (`.source` metadata files), optional script import
  - Sourced subdirectory layout (`~/.openjarvis/skills/<source>/<name>/`)

- **Skills learning loop** — trace tagging, pattern discovery, DSPy/GEPA optimization.
  - Trace metadata tagging: `skill`, `skill_source`, `skill_kind` flow through ToolExecutor -> TraceCollector -> TraceStep
  - `SkillDiscovery` wired into `SkillManager.discover_from_traces()` with kebab name normalization
  - `SkillOptimizer` — per-skill DSPy/GEPA wrapper that buckets traces and writes sidecar overlays
  - `SkillOverlay` — sidecar storage at `~/.openjarvis/learning/skills/<name>/optimized.toml`
  - `SkillManager._load_overlays()` applies optimized descriptions + few-shot examples at discovery time
  - `LearningOrchestrator._maybe_optimize_skills()` — opt-in auto-trigger

- **Skills benchmark harness** — 4-condition PinchBench evaluation.
  - I3 fix: `skill_few_shot_examples` wired through SystemBuilder -> `_run_agent` -> `ToolUsingAgent` -> `native_react.REACT_SYSTEM_PROMPT`
  - `SkillBenchmarkRunner` — 4-condition x N-seed x M-task sweep with markdown report
  - `JarvisAgentBackend` accepts `skills_enabled` and `overlay_dir` kwargs
  - Conditions: `no_skills`, `skills_on`, `skills_optimized_dspy`, `skills_optimized_gepa`

- **CLI commands:**
  - `jarvis skill list` / `info` / `run` / `install` / `sync` / `sources` / `update` / `remove` / `search`
  - `jarvis skill discover` — mine traces for recurring tool patterns
  - `jarvis skill show-overlay` — inspect optimization output
  - `jarvis optimize skills` — run DSPy/GEPA per-skill optimization
  - `jarvis bench skills` — run the PinchBench skills benchmark

- **Agent prompt improvement:**
  - `native_react.REACT_SYSTEM_PROMPT` now includes "Using Skills" guidance that teaches agents to distinguish executable vs. instructional skill responses
  - `{skill_examples}` placeholder for optimized few-shot example injection

- **Configuration:**
  - `[skills]` section: `enabled`, `skills_dir`, `active`, `auto_discover`, `auto_sync`, `max_depth`, `sandbox_dangerous`
  - `[[skills.sources]]` section: `source`, `url`, `filter`, `auto_update`
  - `[learning.skills]` section: `auto_optimize`, `optimizer`, `min_traces_per_skill`, `optimization_interval_seconds`, `overlay_dir`
  - `SkillSourceConfig` and `SkillsLearningConfig` dataclasses

- **Documentation:**
  - `docs/user-guide/skills.md` — comprehensive user guide
  - `docs/architecture/skills.md` — technical deep-dive
  - `docs/tutorials/skills-workflow.md` — end-to-end tutorial
  - `docs/getting-started/configuration.md` — expanded with skills config sections
  - `CLAUDE.md` — updated architecture section

### Fixed

- **Trace metadata flow** — `ToolResult.metadata` now propagates through `TOOL_CALL_END` event to `TraceStep.metadata` (was silently dropped at the event-bus boundary)
- **TaintSet JSON serialization** — `ToolExecutor._json_safe_metadata()` filters non-JSON-serializable values (like `TaintSet`) from event payloads before they reach `TraceStore`
- **Non-dict YAML frontmatter** — source resolvers handle `yaml.safe_load()` returning a string instead of a dict (discovered on real OpenClaw imports)
- **OpenClaw category/name queries** — `jarvis skill install openclaw:owner/slug` now correctly splits into category + name match
- **SkillDiscovery trace compatibility** — `_extract_tool_sequence` reads from `step.input["tool"]` (the actual `TraceStep` format), not the nonexistent `step.tool_name` attribute
- **LearningOrchestrator skill trigger** — `_maybe_optimize_skills` runs BEFORE the SFT-data short-circuit (skills are tagged via trace metadata, not mined as SFT pairs)
- **PinchBenchScorer constructor** — `SkillBenchmarkRunner` constructs `PinchBenchScorer(judge_backend, model)` instead of no-args
- **EvalRunner results access** — reads per-task data from `eval_runner.results` property, not nonexistent `summary.results`
