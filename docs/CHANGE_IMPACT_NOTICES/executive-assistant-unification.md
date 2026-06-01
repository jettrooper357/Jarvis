# Change Impact Notice: Executive Assistant Unification

- **Date:** 2026-05-29
- **Status:** Approved (design + plan approved in the 2026-05-29 brainstorming
  session; see `docs/superpowers/specs/2026-05-29-executive-assistant-unification-design.md`
  and `docs/superpowers/plans/2026-05-29-executive-assistant.md`)
- **Approval required:** Yes — granted by the user during brainstorming.

## What is changing

A unified Executive Assistant capability layer is added, where the Chief
Orchestrator *is* the Executive Assistant. The change is additive:

- **New package** `src/openjarvis/assistant/` with two SQLite-backed stores:
  - `followups/store.py` — `FollowUpStore` (Follow-Up Tracker).
  - `decisions/store.py` — `DecisionLogStore` (Decision Log).
- **New tools** (`@ToolRegistry.register`): `followup_add`, `followup_list`,
  `followup_resolve`, `followup_sweep_stale`, `decision_record`,
  `decision_list` (in `tools/followup_tools.py` and `tools/decision_tools.py`,
  wired into `tools/__init__.py`).
- **5 new `EventType` members** in `core/events.py`: `followup.created`,
  `followup.updated`, `followup.resolved`, `decision.recorded`,
  `decision.superseded`.
- **Feature-flagged Chief prompt block**: `build_chief_system_prompt(...)`
  gains an `assistant_mode` parameter (default **False**). When off, the prompt
  is byte-for-byte identical to prior behavior.
- **Two new subordinate agent templates**: `decision_recorder.toml`,
  `priority_advisor.toml`.

## Why the change is needed

The user wanted a cohesive Executive Assistant (daily briefing, inbox triage,
follow-up tracking, decision log). Briefing and triage already exist
(`morning_digest`, `inbox_triager`); the two missing pieces are the Follow-Up
Tracker and Decision Log, plus an EA identity that coordinates everything under
the single Chief ingress.

## Benefits

- Durable, auditable tracking of "waiting on X" / "owe a reply" items and of
  decisions/approvals (with who + when), linked to projects/tasks.
- One coherent assistant experience under the existing Chief ingress.
- No regression risk to existing behavior (opt-in via flag; wrapped agents
  untouched).

## Risks and mitigations

- **Risk:** The Chief prompt is a core, protected component.
  **Mitigation:** Change is additive and gated by `assistant_mode` defaulting
  off; a regression test asserts the default prompt is unchanged, and the
  existing chief/orchestrator suites (43 tests) pass.
- **Risk:** New SQLite files on disk.
  **Mitigation:** They auto-create under `~/.openjarvis/` (`followups.db`,
  `decisions.db`); deletable with no impact on other subsystems.

## Affected files / modules

Created: `src/openjarvis/assistant/__init__.py`,
`src/openjarvis/assistant/followups/{__init__,store}.py`,
`src/openjarvis/assistant/decisions/{__init__,store}.py`,
`src/openjarvis/tools/followup_tools.py`,
`src/openjarvis/tools/decision_tools.py`,
`src/openjarvis/agents/templates/decision_recorder.toml`,
`src/openjarvis/agents/templates/priority_advisor.toml`, plus tests under
`tests/assistant/`, `tests/tools/`, `tests/agents/`, `tests/core/`.

Modified: `src/openjarvis/core/events.py` (enum members),
`src/openjarvis/tools/__init__.py` (imports),
`src/openjarvis/agents/templates/chief_prompt.py` (`assistant_mode`).

## User-visible behavior changes

None by default. The EA prompt block only activates when `assistant_mode` is
enabled (config `[assistant].enabled`). The new tools are available to agents
once registered but do nothing unless invoked.

## Migration steps

None. The new stores create their own SQLite databases on first use.

## Rollback steps

1. `git revert` the commit range for this change.
2. Optionally delete `~/.openjarvis/followups.db` and
   `~/.openjarvis/decisions.db`.

No other subsystem depends on these stores, so rollback is clean.
