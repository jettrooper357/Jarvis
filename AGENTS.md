# Codex Operating Contract

Before any architecture or implementation work, Codex must treat this file as the governing project instruction set for Jarvis.

Priority order for this repository:
1. Preserve the current OpenJarvis foundation and all protected augmented features.
2. Route architectural work toward a Chief Orchestrator ingress, hierarchical delegation, durable task/event ledgers, persistent sessions, policy-based capabilities, and safe live observability.
3. Perform the required audit/plan/approval workflow before risky implementation.
4. Prefer additive adapters, wrappers, feature flags, and backwards-compatible migrations over rewrites.
5. Never remove, degrade, replace, or silently bypass a current feature without explicit approval.
6. Never expose hidden chain-of-thought in logs, UI, task records, traces, or agent-to-agent messages.

Required docs for this program of work:
- `docs/ARCHITECTURE_DRIFT_REPORT.md`
- `docs/AUGMENTED_FEATURES.md`
- `docs/FEATURE_PRESERVATION_MATRIX.md`
- `docs/HIERARCHICAL_AGENT_IMPLEMENTATION_PLAN.md`
- `docs/CHANGE_IMPACT_NOTICES/<slug>.md` for any breaking or risky change

If a requested implementation would change an API contract, persistence shape, user workflow, protected feature, or subsystem boundary, Codex must create a Change Impact Notice and stop for approval before implementing that portion.

# Repository Guidelines

## Project Structure & Module Organization

OpenJarvis is a mixed Python, Rust, and TypeScript project. Core Python code lives in `src/openjarvis/`; tests are grouped by domain in `tests/` such as `tests/tools/`, `tests/engine/`, and `tests/connectors/`. The Vite/React UI is in `frontend/`, with Tauri desktop code in `frontend/src-tauri/`. Rust workspace crates live under `rust/crates/`. Documentation is in `docs/`, examples in `examples/`, deployment assets in `deploy/`, shared images in `assets/`, and default TOML config in `configs/openjarvis/`.

## Build, Test, and Development Commands

- `uv sync --extra dev`: install Python development dependencies.
- `uv run pytest tests/ -v`: run the Python test suite.
- `uv run pytest tests/tools/test_file_read.py -v`: run a focused test file.
- `uv run ruff check src/ tests/`: lint Python code.
- `uv run ruff format --check src/ tests/`: verify Python formatting.
- `cd frontend && npm install`: install frontend dependencies.
- `cd frontend && npm run dev`: start the Vite development server.
- `cd frontend && npm run build`: type-check and build the frontend.
- `cd rust && cargo test`: run Rust workspace tests.

## Coding Style & Naming Conventions

Python targets 3.10+ and uses Ruff for linting and formatting. Keep imports sorted and follow existing module patterns in `src/openjarvis/`. Python files and functions use `snake_case`; classes use `PascalCase`. React components use `PascalCase` filenames, hooks use `useSomething.ts`, and shared UI primitives live in `frontend/src/components/ui/`. Rust crates follow standard `rustfmt` conventions.

## Testing Guidelines

Add tests in the closest existing domain directory under `tests/`. Name Python tests `test_*.py` and test functions `test_*`. Use markers declared in `pyproject.toml` for environment-sensitive tests, including `slow`, `cloud`, `docker`, `nvidia`, `amd`, `apple`, and `live`. Prefer focused unit tests for small changes and integration coverage for public tools, engines, agents, connectors, or workflow behavior.

## Commit & Pull Request Guidelines

Commit history follows Conventional Commits, for example `feat(project): add milestone filters`, `fix: handle empty tool responses`, or `docs: update setup guide`. Keep the first line under 72 characters and reference issues when relevant.

Pull requests should stay focused, describe the behavior change, list tests run, and include screenshots for frontend-visible changes. Discuss large refactors, new dependencies, or core abstraction changes before opening a PR.

## Security & Configuration Tips

Do not commit credentials, API keys, local databases, generated model artifacts, or personal config. Keep reusable defaults in `configs/openjarvis/` and document new environment variables or optional extras in `docs/` when adding integrations.

# JARVIS Foundation Guide

Status: Canonical architecture and implementation guardrail  
Applies to: all coding agents, reviewers, maintainers, and automated refactoring tools  
Canonical location: `AGENTS.md`  
Mirror for Claude Code: `CLAUDE.md`

## Purpose

This file defines the non-negotiable architecture, runtime contracts, change-control rules, and testing requirements for the Jarvis application.

The goal is to keep Jarvis aligned with its OpenJarvis foundation while preserving and extending the augmented features already added to this project.

If code, prompts, UI, or tests conflict with this file, this file wins unless the user explicitly approves a change.

## Mission

Jarvis is a local-first, multi-surface AI agent platform with a hierarchical chain of command.

The system must:
- accept tasks from the chat page and the agent-interact page,
- route all inbound work through the Chief Orchestrator,
- let the Chief complete the work or delegate it down the hierarchy,
- require all subordinate work to flow back up the chain of command,
- present the final result, follow-up question, error, or progress update through the Chief,
- preserve all currently working features unless the user approves changes.

## North-star architecture

Jarvis has four planes:

### Control plane
Owns:
- agent registry
- org hierarchy
- manager/subordinate relationships
- skill/preset/datasource assignment
- task ledger
- approvals
- routing rules
- effective capability computation

### Runtime plane
Owns:
- agent turns
- delegation
- tool calls
- background execution
- scheduling
- worker sessions
- execution sandboxes
- model/engine dispatch

### Data plane
Owns:
- session history
- knowledge stores
- traces
- telemetry
- uploaded files
- agent notes/state
- capability metadata

### Experience plane
Owns:
- chat page
- agent-interact page
- agent overview
- org chart
- conversation log sidebar
- capability inspector
- telemetry/dashboard surfaces

## Non-negotiable architecture invariants

### Chief Orchestrator is the only human-facing ingress
All requests from the chat page and the agent-interact page must enter through the Chief Orchestrator.

No subordinate agent may become a direct human-facing ingress path unless the user explicitly approves that design.

### Delegation must be hierarchical and reversible
The Chief may:
- execute directly,
- delegate to one subordinate,
- split work into subtasks.

Every delegated task must:
- have a parent task,
- have an owning agent,
- have an append-only event trail,
- be able to return status upward,
- be cancellable,
- be resumable when possible,
- preserve sufficient context for audit/debugging.

### Upward return path is mandatory
Subordinate agents do not deliver final answers directly to the user.

Subordinate agents return:
- completion results,
- blocking questions,
- errors,
- progress events,
- artifacts,
- tool outcomes,
- recommended next actions

to their parent agent, eventually rolling back up to the Chief Orchestrator.

### Preserve augmented features
Current project-specific features are protected.

Before changing architecture, the agent must first inventory all existing augmented features and update:
- `docs/AUGMENTED_FEATURES.md`
- `docs/FEATURE_PRESERVATION_MATRIX.md`

No protected feature may be removed, merged away, or functionally degraded without an approved Change Impact Notice.

### Additive change is preferred over replacement
Prefer:
- adapters,
- wrappers,
- feature flags,
- compatibility layers,
- schema migrations,
- incremental refactors

over rewrites.

Do not replace a subsystem just because another framework does it differently.

## Task model

Every inbound request becomes a root task.

Each task must support:
- `id`
- `parent_id`
- `root_id`
- `request_source`
- `requesting_user`
- `assigned_agent_id`
- `status`
- `priority`
- `created_at`
- `updated_at`
- `completed_at`
- `summary`
- `artifacts`
- `errors`
- `requires_user_input`
- `requires_approval`

### Required statuses
Use a stable task lifecycle:

- `received`
- `triaged`
- `planned`
- `delegated`
- `in_progress`
- `blocked`
- `awaiting_input`
- `awaiting_approval`
- `completed`
- `failed`
- `cancelled`

Do not invent ad hoc status strings without updating shared types, UI mappings, persistence, and tests.

## Event model

All important runtime behavior must emit structured events.

Minimum event families:
- `task.created`
- `task.updated`
- `task.delegated`
- `task.completed`
- `task.failed`
- `agent.turn.started`
- `agent.turn.finished`
- `agent.message`
- `tool.started`
- `tool.finished`
- `memory.read`
- `memory.write`
- `approval.requested`
- `approval.resolved`
- `ui.notification`

### Event logging rules
- Use append-only event storage for auditability.
- Never rely on mutable UI state as the source of truth.
- The UI may derive conversation logs from events, but it must not be the canonical store.
- Do not expose hidden chain-of-thought. Expose operational summaries, delegation messages, status changes, tool activity, and user-safe rationale only.

## Session and memory rules

### Session ownership
- The Chief has a primary user-facing session.
- Child tasks may have isolated worker sessions.
- Worker sessions must be linkable to their parent task and parent agent.
- Session isolation is required for long-running or parallel subordinate work.

### Memory
Jarvis may use:
- conversational/session memory,
- knowledge retrieval,
- agent notes/state,
- telemetry/traces.

Memory retrieval must always preserve source attribution where applicable.

## Capability model

Skills, presets, tools, and datasources are not cosmetic tags.
They are policy-controlled capabilities.

Each agent must expose:
- assigned capabilities
- inherited capabilities
- blocked capabilities
- effective capabilities
- approval-required capabilities

### Capability inheritance
Use this order:
1. system defaults
2. role/profile defaults
3. manager-imposed allowances/restrictions
4. agent-local assignments
5. temporary task-scoped overrides

The UI must clearly distinguish:
- available
- assigned
- inherited
- effective
- disabled
- protected

## UI rules

### Capability Inspector
The capability editor must be backed by policy/state, not just UI chips.

The user must be able to:
- add/remove skills
- add/remove presets
- add/remove datasources
- understand inherited vs effective runtime capability
- see what changed
- see whether a change requires approval or restart

### Agent Overview
The Agents page must show:
- the org hierarchy,
- runtime status,
- task ownership,
- recent agent activity,
- a live right-side conversation/event log.

The sidebar log should display:
- agent-to-agent handoffs,
- task progress,
- blocking questions,
- tool milestones,
- completion notices,
- failures,
- approval requests

without exposing hidden reasoning.

## Security and approvals

Any action that can:
- modify files,
- run shell/system commands,
- access remote services,
- change agent hierarchy,
- alter capability policy,
- delete data,
- mutate schemas,
- disable protections

must be explicitly governed by approvals, policy, or both.

Dangerous capabilities must be:
- allowlisted,
- scope-limited,
- auditable,
- reversible where possible.

## Change-control protocol

### No silent removal
Never silently remove or materially degrade:
- a UI surface,
- an API route,
- a background capability,
- a tool,
- a data source,
- a telemetry/tracing surface,
- an existing user workflow.

### Required document for breaking or risky changes
If a change is not purely additive, create:
`docs/CHANGE_IMPACT_NOTICES/<slug>.md`

The notice must include:
- what is changing
- why the change is needed
- benefits
- risks
- affected files/modules
- user-visible behavior changes
- migration steps
- rollback steps
- whether explicit approval is required

If explicit approval is required, stop implementation after preparing the notice and wait.

## Implementation rules for coding agents

Before coding:
1. Read this file.
2. Inventory impacted features.
3. Identify all affected modules, routes, schemas, and tests.
4. Prefer the smallest viable change.
5. Plan migrations before edits.

While coding:
- preserve module boundaries,
- preserve public contracts unless approved to change them,
- add feature flags for transitional behavior,
- update shared types before UI wiring,
- keep persistence and event schemas in sync,
- add logging and tests with the code change.

After coding:
- run linting
- run unit tests
- run integration tests
- run UI/build validation for touched surfaces
- update docs
- update capability/architecture inventory if needed

## Testing standard

Every meaningful change must include tests at the right level.

### Unit tests
Required for:
- task state transitions
- event emission
- capability resolution
- hierarchy/routing helpers
- serializer/schema logic

### Integration tests
Required for:
- Chief -> subordinate delegation
- subordinate -> parent return path
- blocked task -> follow-up question flow
- failure propagation
- approval gating
- session persistence
- background task resume/replay
- websocket/event stream payloads

### UI tests
Required for touched UI:
- agent overview rendering
- org chart interactions
- capability editor behavior
- live sidebar event log behavior
- status badge transitions

### Regression tests
Required whenever touching existing features:
- preserve current routes and user workflows
- preserve current augmented features
- preserve existing tool wiring unless explicitly changed
- preserve current visual theme unless the task is a design update

## Definition of done

A task is only done when:
- the feature works,
- existing protected behavior still works,
- tests pass,
- docs are updated,
- event/log emissions are correct,
- no unapproved destructive changes remain,
- the Chief Orchestrator can still explain the task outcome to the user.

## Forbidden behaviors

Do not:
- bypass the Chief Orchestrator for user-facing completion,
- let subordinates become silent dead ends,
- delete current features to make the architecture “cleaner,”
- replace durable task records with ephemeral in-memory state,
- rely on the UI as the source of truth,
- expose hidden chain-of-thought in logs,
- introduce breaking changes without a Change Impact Notice and approval,
- collapse capability policy into hard-coded conditionals.

If a proposed change conflicts with this guide, stop and surface the conflict clearly.
