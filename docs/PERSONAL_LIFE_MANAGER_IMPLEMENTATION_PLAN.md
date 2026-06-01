# Personal Life Manager Implementation Plan

> Status: Additive feature plan, generated 2026-05-29.
> Inputs: `AGENTS.md`, `docs/AUGMENTED_FEATURES.md`,
> `docs/FEATURE_PRESERVATION_MATRIX.md`, and the requested Personal Life
> Manager feature list.

## Scope

The Personal Life Manager program adds life-domain planning, routines,
reminders, knowledge notebooks, and specialist personal agents while preserving
Chief Orchestrator ingress, durable task/event ledgers, per-agent jobs, project
task linkage, capability policy, and live observability.

## Requested Feature Map

| Requested area | Jarvis implementation path | Approval risk |
| --- | --- | --- |
| Life domains: Work, Church, Family, Health, Finances, Learning, Home, Personal goals | Add domain taxonomy to dashboard/project filtering, agent prompts, and optional task metadata. | Medium if metadata schema changes; low if prompt/config only. |
| Personal Planning Dashboard: Today, This week, This month, Long-term goals | Add a dashboard surface derived from project tasks, agent tasks, and agent jobs. | Medium; touches UI workflow and possibly task metadata. |
| Habit / Routine Tracking | Use protected Agent Jobs and project tasks; optionally add habit-specific views later. | Low for job presets, medium for new habit schema. |
| Personal Reminder System | Use Agent Jobs for recurring/once reminders and project tasks for lists. | Low for presets, medium for new reminder UI. |
| Study / Knowledge Notebook | Use knowledge ingestion/search, notes, memory, and project documentation. | Low if using existing knowledge tools. |
| Life Manager Agent | Built-in agent template. | Low. |
| Sermon / Study Agent | Built-in agent template. | Low. |
| Health Routine Agent | Built-in agent template. | Low. |
| Finance Reminder Agent | Built-in agent template. | Low. |
| Learning Coach Agent | Built-in agent template. | Low. |

## Phase 1: Additive Agent Templates

- Add built-in templates: `life_manager`, `sermon_study`, `health_routine`,
  `finance_reminder`, and `learning_coach`.
- Keep all agents subordinate to Chief routing by policy and prompt.
- Use existing tools only: project task tools, managed-agent tools, memory,
  knowledge search, and research tools.
- No schema, route, or workflow changes.

## Phase 2: Job and Reminder Presets

- Add optional examples or seed helpers for common jobs:
  Bible study, workouts, sermon prep, project review, household tasks,
  bills, appointment preparation, shopping lists, and weekly/monthly planning.
- Preserve `agent_jobs` and `agent_job_runs` as the durable source of truth.
- Do not create UI-only reminder state.

## Phase 3: Personal Planning Dashboard

- Add a dashboard view derived from existing durable sources:
  project tasks, agent tasks, agent jobs, and task events.
- Initial filters: Today, This week, This month, Long-term goals, domain,
  assigned agent, status, and blocked/approval-needed.
- This phase changes user workflow and likely touches frontend route/state, so
  implementation should be approved before coding.

## Phase 4: Optional Domain Metadata

- If domain filtering needs durable metadata beyond project categories, add a
  backwards-compatible task metadata field or domain assignment adapter.
- Any non-additive schema or API change requires a Change Impact Notice before
  implementation.

## Protected Behavior

- Chief Orchestrator remains the only human-facing ingress.
- Subordinate personal agents return results upward through the hierarchy.
- Agent Jobs remain per-agent durable records, not a global-only reminder list.
- Project and agent tasks remain linked through protected project-task fields.
- Capability policy remains the source of truth for available tools.
- No hidden chain-of-thought is logged, displayed, stored, or delegated.

## Tests Required By Phase

- Phase 1: template discovery and instantiation tests.
- Phase 2: scheduler/job regression tests for each preset type introduced.
- Phase 3: frontend rendering tests for planning filters and event-derived
  status, plus API contract tests for any new dashboard endpoint.
- Phase 4: migration/backfill tests and compatibility tests for old task rows.

## Approval Gate

Dashboard implementation, durable domain metadata, schema changes, new API
contracts, or changes to existing task/reminder workflows require explicit
approval before coding.
