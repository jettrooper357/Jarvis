# Agent Org

Jarvis runs a hierarchical chain of command. The **Chief Orchestrator** is the
only human-facing ingress; it delegates to managers, who delegate to
specialists, and all results flow back up the chain. This page covers the
default org and how to stand it up.

## The default hierarchy

```
Chief Orchestrator
├─ Executive Assistant → Inbox Analyst, Calendar, Follow-Up
├─ Workflow Manager   → Project Planner, Timeline, Risk Analyst
├─ CTO / Architect    → Code Developer, Code Reviewer, Test Engineer, SQL Engineer, Deployment
├─ Knowledge Manager  → Document Indexing, Research, Notes
└─ Life Manager       → Church / Sermon, Health, Finance, Personal Goals
```

Each role is backed by an agent **template** (a capability blueprint: tools,
prompt, schedule). A template's optional `org_role` field is its default
placement when an agent is created from it; an explicit `org_role` at create
time always wins.

## Bootstrapping the org

The default tree is **opt-in** and stood up by an **idempotent** bootstrap —
safe to re-run, it only fills in roles that don't already exist.

**REST:**

```
POST /v1/org/bootstrap     → {"created": [...], "skipped": [...], "chief_id": "..."}
GET  /v1/org               → {"org": { ...nested tree rooted at the Chief... }}
```

`POST /v1/org/bootstrap` returns 503 if the server has no agent manager.
`GET /v1/org` returns `{"org": null}` until a Chief exists.

**CLI:**

```bash
jarvis org bootstrap      # create the default org (idempotent)
jarvis org show           # print the current hierarchy
```

## How org placement works

The bootstrap walks a code-defined blueprint (`DEFAULT_ORG` in
`openjarvis/agents/org.py`) in dependency order — Chief first, then managers,
then specialists — so each agent's `manager_agent_id` resolves to an
already-created manager. Exactly one agent is designated Chief
(`is_chief`). You can re-parent or remove agents afterward with the existing
agent-management APIs (`update_agent(manager_agent_id=...)`).

## Invariants

- Exactly one Chief; the Chief remains the sole human-facing ingress.
- Subordinates return results **upward** to their manager / the Chief — they
  never deliver directly to the user.
- Agents never expose hidden reasoning; only user-safe summaries.

## Out of scope (current)

Auto-running the bootstrap at startup, org editing via dedicated REST routes
(use `update_agent`), and the org-chart UI are deferred to later slices.
