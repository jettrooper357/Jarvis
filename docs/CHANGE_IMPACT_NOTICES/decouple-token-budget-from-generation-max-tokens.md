# Change Impact Notice: Decouple lifetime token budget from generation `max_tokens`

## What is changing

The agent budget enforcer in `AgentExecutor` previously read `config["max_tokens"]`
as a **cumulative lifetime token budget**. That same `config["max_tokens"]` key is
the **per-completion generation output limit** used everywhere else (every agent
class passes `max_tokens=self._max_tokens` to generation; the chat path reads
`config.get("max_tokens", 1024)`).

This change introduces a dedicated budget key, `budget_max_tokens`, for the
lifetime token cap. Generation `max_tokens` no longer trips the budget enforcer.
The cost budget (`max_cost`) is unchanged — it was already a dedicated key.

## Why the change is needed

The collision permanently broke long-running agents. The Chief
(`monitor_operative`, whose `_default_max_tokens = 4096`) stored `max_tokens: 4096`
as its generation cap. The executor interpreted 4096 as a lifetime budget, so once
cumulative tokens crossed 4096 (one multi-turn run) the agent flipped to
`budget_exceeded` and stayed there — even though the UI showed **Budget: Unlimited**
(that row only reflects `max_cost`).

## Benefits

- Agents stop being falsely marked `budget_exceeded` from a normal generation setting.
- The "Budget" capability becomes coherent: cost via `max_cost`, lifetime tokens via
  `budget_max_tokens`, generation length via `max_tokens`.

## Risks

- Any agent that *intentionally* relied on `max_tokens` as a lifetime budget would
  lose that enforcement. There is no UI that sets it that way and no such usage in
  the codebase, so practical risk is low.

## Affected files / modules

- `src/openjarvis/agents/executor.py` — budget enforcement reads `budget_max_tokens`.
- `src/openjarvis/agents/manager.py` — self-heal recompute reads `budget_max_tokens`.
- `tests/agents/test_budget.py` — token-budget tests use the new key.

## User-visible behavior changes

- The Chief (and similar long-running agents) no longer show a stuck
  `budget exceeded` badge caused by their generation `max_tokens`.
- A lifetime token budget is now set via `budget_max_tokens` in agent config.

## Migration steps

- No data migration required. Existing `max_tokens` values continue to act as the
  generation limit. To impose a lifetime token cap, set `budget_max_tokens`.
- Stuck agents clear on the next config edit (self-heal) or via the recover action.

## Rollback steps

- Revert the executor/manager changes to read `max_tokens` for the budget check.

## Approval

Requested and approved by the user in-session ("fix the underlying bug" / "Both").
