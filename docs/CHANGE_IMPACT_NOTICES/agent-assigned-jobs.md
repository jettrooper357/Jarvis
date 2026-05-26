# Change Impact Notice: Agent Assigned Jobs

## What Would Change

Add a first-class, per-agent Jobs system that can be configured from each agent's Overview page.

Planned job types:
- `cron`: run on a cron expression, for example every weekday at 9 AM.
- `interval`: run every N seconds/minutes/hours.
- `once`: run once at a specific date/time.
- `if_this_then_that`: evaluate a trigger condition and run an action when the condition becomes true.
- `event`: run when a Jarvis event family is emitted, such as `task.failed`, `approval.resolved`, or `memory.write`.
- `webhook`: optional future job type for inbound HTTP events, approval-gated.
- `manual`: saved reusable job that can be run on demand from the UI.

The job model would be persisted separately from `agent_tasks` so recurring automation does not pollute the task ledger until a job actually fires. Each fired job would create or enqueue an auditable root task routed through the Chief Orchestrator, then delegated to the assigned agent when policy allows.

The agent Overview page would gain a Jobs section for listing, creating, pausing, resuming, deleting, and manually running jobs assigned to that agent.

Jobs would also become capability-governed runtime objects, not just UI records. Each job would declare:
- required capabilities such as `job:create`, `job:update`, `job:run`, `job:delegate`, `schedule:create`, `tool:use`, or datasource/tool-specific capabilities.
- assigned agent, inherited manager constraints, blocked capabilities, approval-required capabilities, and effective capabilities at fire time.
- whether the job may delegate, which subordinate agents are eligible, and what capabilities may be passed down as task-scoped overrides.

Delegable jobs would follow the existing hierarchy invariant:
- the job trigger creates a Chief-routed root task,
- the Chief may execute directly or delegate down the org tree,
- subordinate work returns to the parent and then back to the Chief,
- job run history records operational summaries, task IDs, statuses, tool milestones, approvals, and artifacts without hidden chain-of-thought.

## Why It Is Needed

The current system has partial scheduling support:
- `openjarvis.agents.scheduler.AgentScheduler` can schedule an entire agent tick from `agent.config.schedule_type` and `schedule_value`.
- `openjarvis.scheduler.TaskScheduler` can schedule generic prompts in a separate `scheduled_tasks` table.
- Agent Overview currently exposes tasks, capabilities, channels, memory, learning, and logs, but not assignable recurring automations.

The requested feature needs multiple jobs per agent, richer trigger types, per-job state, UI management, and durable run history.

## Benefits

- Supports multiple automations per agent instead of one schedule embedded in `managed_agents.config_json`.
- Keeps each job explicitly assigned to an agent while preserving Chief Orchestrator ingress for fired work.
- Makes jobs part of the same policy-controlled capability model as skills, presets, tools, and datasources.
- Allows jobs to be delegated safely when the assigned agent needs subordinate execution.
- Separates job definitions from task executions and task ledgers.
- Gives users one place on the agent Overview to manage recurring, conditional, and manual automations.
- Provides an additive bridge from existing cron/interval scheduling to richer IFTTT-style behavior.

## Risks

- Persistence shape changes are required for job definitions, job runs, and possibly trigger cursors.
- New API contracts are required for job CRUD and job run actions.
- Runtime behavior changes are required so fired jobs create auditable tasks/events rather than bypassing the Chief.
- Capability resolution must be checked at job creation, update, manual run, scheduled fire, and delegation time.
- Delegated jobs need strict scope handling so a subordinate cannot inherit broader capabilities than the parent/job permits.
- Conditional jobs can become noisy or unsafe without cooldowns, dedupe keys, and approval gating.
- Webhook/event jobs may expose sensitive data if payloads are logged without sanitization.
- Scheduled jobs can repeatedly trigger tool use, file writes, or remote-service access, so capability policy and approvals must be enforced at fire time.

## Side Effects

- Agent Overview will gain a new jobs management surface.
- Existing per-agent `schedule_type` / `schedule_value` config may need to be displayed as a legacy schedule or migrated into jobs.
- Scheduler startup/reconciliation may need to register active jobs, not only agents.
- New events should be emitted, likely `job.created`, `job.updated`, `job.triggered`, `job.run.started`, `job.run.finished`, `job.failed`, and `job.paused`.
- Capability Inspector will need to show job-related capabilities and whether a selected agent can create, run, receive, or delegate jobs.
- Agent-to-agent delegation logs should include job-originated tasks without exposing hidden reasoning.
- Tests must cover persistence, API, scheduler triggering, Chief routing, approval gating, and UI flows.

## Migration Path

Use an additive schema migration:
- Create `agent_jobs` with durable job definitions.
- Create `agent_job_runs` with append-only run history.
- Optionally create `agent_job_cursors` for IFTTT/event trigger state.
- Do not remove existing `agent.config.schedule_type` or `schedule_value`.
- For existing agents with non-manual `schedule_type`, either:
  - leave the legacy scheduler untouched and show it as "Legacy schedule", or
  - create disabled draft job records for review before migration.

Recommended first implementation:
- Add `agent_jobs` and `agent_job_runs`.
- Add job capability fields in the job definition, likely JSON columns for `required_capabilities`, `approval_required_capabilities`, `delegation_policy`, and `task_overrides`.
- Support `cron`, `interval`, `once`, and `manual` first.
- Add `if_this_then_that` only for internal state predicates that are safe and testable, such as task status, unread channel count, or data-source sync status.
- Defer inbound `webhook` jobs until a separate approval notice unless explicitly approved now.

## Rollback Path

- Disable the feature flag for agent jobs.
- Stop registering jobs with the scheduler.
- Hide the Jobs section in Agent Overview.
- Leave `agent_jobs` and `agent_job_runs` tables intact for audit; do not delete data automatically.
- Existing agent scheduling via `config.schedule_type` / `schedule_value` remains untouched.

## Exact Files Affected

Likely backend files:
- `src/openjarvis/agents/manager.py`
- `src/openjarvis/agents/scheduler.py`
- `src/openjarvis/agents/executor.py`
- `src/openjarvis/agents/capabilities.py`
- `src/openjarvis/agents/approvals.py`
- `src/openjarvis/server/agent_manager_routes.py`
- `src/openjarvis/core/events.py`
- `src/openjarvis/security/capabilities.py`
- `src/openjarvis/core/config.py`

Likely frontend files:
- `frontend/src/lib/api.ts`
- `frontend/src/pages/AgentsPage.tsx`
- possibly `frontend/src/types/index.ts`

Likely tests:
- `tests/agents/` or nearest existing agent manager/scheduler tests
- `tests/server/` for API routes
- frontend tests if the repository has matching UI test patterns for Agents page changes

Docs to update after implementation:
- `docs/AUGMENTED_FEATURES.md`
- `docs/FEATURE_PRESERVATION_MATRIX.md`
- `docs/HIERARCHICAL_AGENT_IMPLEMENTATION_PLAN.md`

## Reversibility

Reversible via feature flag and route/UI hiding. Data migrations are additive and should not require destructive rollback.

## Approval Question

Do you approve implementing this change as an additive, feature-flagged Agent Jobs system with:
- per-agent persisted jobs,
- `cron`, `interval`, `once`, `manual`, and initial safe `if_this_then_that` job types,
- full integration with agent capability resolution and the Capability Inspector,
- delegation policy for jobs that may require subordinate execution,
- job firing routed through the Chief Orchestrator before delegation,
- job events and append-only run history,
- a Jobs section on each agent Overview,
- no removal of the existing per-agent scheduler config?

Inbound webhook-triggered jobs should remain out of scope unless separately approved.
