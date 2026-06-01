# Change Impact Notice: Personal Planning Dashboard

Status: Approved by user on 2026-05-29

## What is changing

Jarvis gains an additive Personal Planning Dashboard route that summarizes
life domains, planning horizons, habits/routines, reminders, and study notebook
work from existing durable sources.

## Why the change is needed

The requested Personal Life Manager feature set needs a first-class planning
surface for Today, This week, This month, Long-term goals, life domains,
routines, reminders, and study/knowledge work.

## Benefits

- Provides one view for personal work across existing projects, tasks, agents,
  and jobs.
- Preserves Agent Jobs and task ledgers as the durable source of truth.
- Avoids a parallel reminder or habit database.
- Keeps personal agents subordinate to Chief Orchestrator governance.

## Risks

- The new dashboard may classify a task into the wrong life domain when source
  text is ambiguous.
- Fetching jobs for all agents can add extra frontend requests on load.
- Users may expect editing from the dashboard; the first implementation is
  read-focused and sends durable edits through existing task/job surfaces.

## Affected files/modules

- `frontend/src/App.tsx`
- `frontend/src/components/Sidebar/Sidebar.tsx`
- `frontend/src/pages/PersonalPlanningPage.tsx`
- `frontend/src/pages/personalPlanningUtils.ts`
- `frontend/src/pages/personalPlanningUtils.test.ts`
- `docs/AUGMENTED_FEATURES.md`
- `docs/FEATURE_PRESERVATION_MATRIX.md`

## User-visible behavior changes

- A new Personal Planning item appears in the sidebar.
- `/life-planner` shows planning metrics, horizon filters, life-domain filters,
  a task/job queue, notebook groupings, and routine highlights.
- Existing Mission Control, Agents, Projects, and Jobs workflows remain intact.

## Migration steps

No database or API migration is required. The dashboard derives from existing
Mission Control, managed-agent, and Agent Jobs endpoints.

## Rollback steps

Remove the route, sidebar item, page, and utility/test files. Existing task,
project, agent, and job data remains unchanged.

## Approval

Explicit approval was given by the user on 2026-05-29 before implementation.
