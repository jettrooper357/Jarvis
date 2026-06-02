# Change Impact Notice: Agent Org Expansion

- **Date:** 2026-06-02
- **Status:** Approved (design + plan approved in the 2026-06-02 brainstorming
  session; see `docs/superpowers/specs/2026-06-02-agent-org-expansion-design.md`
  and `docs/superpowers/plans/2026-06-02-agent-org-expansion.md`)
- **Approval required:** Yes — granted by the user during brainstorming.

## What is changing

Sub-project 5 of the Autonomous Workflow Engine. Additive; reuses the existing
runtime org model (no schema change):

- **New module** `src/openjarvis/agents/org.py`: the `OrgRole` dataclass, the
  `DEFAULT_ORG` blueprint (Chief → 5 managers → specialists, 24 roles), and the
  idempotent `bootstrap_default_org(manager)` + `build_org_tree(manager)`.
- **15 new role templates** under `agents/templates/` (chief_orchestrator,
  executive_assistant, workflow_manager, cto_architect, knowledge_manager,
  calendar_agent, followup_agent, timeline_agent, risk_analyst, code_developer,
  test_engineer, sql_engineer, deployment_agent, doc_indexing_agent,
  notes_agent).
- **`org_role` field added** to 9 existing reused templates.
- **`create_from_template` change**: when the caller passes no `org_role`, it
  falls back to the template's `org_role` field; `org_role`/`manager_role` are
  popped from the template config so they don't leak into the agent's
  `config_json`.
- **New REST routes** `GET /v1/org` + `POST /v1/org/bootstrap` (mounted via
  `include_all_routes`).
- **New CLI** `jarvis org bootstrap` / `jarvis org show`.

## Why the change is needed

The runtime org model (`org_role` / `manager_agent_id` / `is_chief`) already
existed, but there was no way to stand up the full intended hierarchy. This
slice supplies the missing role templates and a one-shot bootstrap that wires
the Chief → managers → specialists tree with correct manager links.

## Benefits

- A complete, instantiable agent org from a single idempotent command.
- Templates carry their default org placement; org-aware creation everywhere.
- A queryable org tree (`GET /v1/org`, `jarvis org show`).

## Risks and mitigations

- **Chief-ingress invariant:** the bootstrap designates exactly one `is_chief`
  (via the existing `set_chief_agent`); all human-facing traffic continues to
  route through the Chief. Subordinate prompts explicitly return results up the
  chain and are not human-facing endpoints.
- **`create_from_template` behavior change:** backward-compatible — the org_role
  fallback only applies when the caller passes none, and org keys are popped
  from config so existing templates/agents are unaffected (verified by the
  existing `test_template_instantiation` + new `test_template_org_role`).
- **Bootstrap side effects:** opt-in (never auto-runs) and idempotent
  (fill-missing by `org_role`; re-running creates nothing).

## Affected files / modules

Created: `src/openjarvis/agents/org.py`,
`src/openjarvis/server/org_routes.py`, `src/openjarvis/cli/org_cmd.py`,
15 templates under `src/openjarvis/agents/templates/`, plus tests under
`tests/agents/`, `tests/server/`, `tests/cli/`.

Modified: `src/openjarvis/agents/manager.py` (create_from_template org_role
fallback), `src/openjarvis/server/api_routes.py` (mount),
`src/openjarvis/cli/__init__.py` (register `org` group), 9 existing templates
(added `org_role`).

## User-visible behavior changes

None unless the bootstrap is run (`POST /v1/org/bootstrap` or
`jarvis org bootstrap`). No existing endpoint, agent, or template behavior
changes.

## Migration steps

None. Run the bootstrap when you want the default org.

## Rollback steps

1. `git revert` the commit range for this change.
2. Archive or delete the agents the bootstrap created (they live in the
   existing `managed_agents` table).

No schema change to roll back.
