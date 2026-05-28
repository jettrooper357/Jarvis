# Change Impact Notice: Chat Shortcut Routing

## What Would Change

Introduce a new subsystem, `openjarvis.shortcuts`, that sits between user-facing ingress (chat + agent-interact routes) and the Chief Orchestrator's first LLM call. When a user message matches a registered shortcut rule, the system:

1. Resolves the rule's target (tool / skill / preset / data-source query) directly.
2. Optionally runs the raw result through a post-processor LLM with a per-rule (or per-target-default) instruction prompt and model.
3. Hands the post-processed content to the Chief as a synthesized `OrchestratorAction(execute_direct, ...)`, so the Chief still owns the task lifecycle, event emission, approvals, and final delivery to the user.

Key surfaces touched:

- **New table** `shortcut_rules` in the primary SQLite store (additive migration).
- **New optional `ToolSpec.metadata["default_post_prompt"]`** key consumed by the post-processor. Existing tools are unaffected.
- **New `pre_turn_hook` parameter on `OrchestratorAgent`** (Chief mode). Default `None`; current Chief behavior is byte-identical when no hook is wired.
- **New config block `[shortcuts]`** in `core/config.py` with `enabled`, `default_post_processor_model`, `seed_builtin_rules_on_first_run`. Defaults to **enabled=false** at first release.
- **New REST endpoints** under `/api/shortcuts` and a new Shortcuts tab in the existing settings/agent-interact UI.
- **New event family** `shortcut.*` on the existing `EventBus`. Existing `tool.*` and `task.*` events still fire from Chief so the conversation log and org-chart sidebar are unchanged.
- **Seeded built-in rules** on first run (when `seed_builtin_rules_on_first_run = true` and `enabled = true`): a `what's the news` family → `tool:get_news`, plus a `news about {topic}` regex.
- **`get_news` tool** ships a `default_post_prompt` ("Rewrite as a concise news-caster narration..."). No behavior change unless a shortcut fires.

Full design lives in `docs/superpowers/specs/2026-05-27-chat-shortcut-routing-design.md`.

## Why It Is Needed

- Today every chat message — including deterministic asks like "what's the news" — pays a Chief LLM round-trip just to decide which tool to call. For an RSS-backed news ask, the LLM step adds seconds and tokens for zero decisional value.
- Users have no first-class way to attach a rewriting instruction to a tool/data-source result. The `get_news` tool already emits text shaped for newscaster narration but relies on the LLM to actually narrate it during its tool-call turn; when the Chief's parser fails (see `chief-function-calling-mode.md`), users see raw RSS dumps.
- Skills/presets/data sources have no fast-path either; everything routes through the LLM.
- The change is additive: the Chief remains the only human-facing ingress and the canonical event source.

## Benefits

- Phrase-deterministic asks skip one LLM call. Expected latency improvement on "what's the news": 5–30s → 1–3s for RSS fetch + post-processor; with a small local formatter model, often sub-second post-processing.
- Per-target post-prompts let users customize result narration without touching code (newscaster vs bullet list vs JSON dump).
- Power users get a single place to map phrases to capabilities; the UI exposes capability policy explicitly, matching the Foundation Guide's "capabilities are policy-controlled" principle.
- Fallback path preserves today's resilience: a failed shortcut by default reverts to a normal Chief LLM turn.

## Risks

- **Recursive firing via preset resolver.** A preset resolver runs a one-shot agent turn, which could itself match a shortcut. Mitigation: pre-turn hook is force-disabled on inner runs the preset resolver spawns; covered by a dedicated test.
- **Catastrophic-backtracking regex.** A user-authored regex could hang the matcher. Mitigation: lazy compile + per-pattern compile-time and match-time budget; offending rule is auto-disabled with a `shortcut.rule.disabled_unsafe` event.
- **Capability/approval drift.** A shortcut could fire an approval-gated tool. Mitigation: approvals run at tool dispatch (`managed_agent_runtime`) regardless of whether the call came from the Chief LLM or a shortcut hook; this path is unchanged.
- **`final_report` shape consumers.** Today the Chief's `FinalReport.summary` carries the user-facing answer. Shortcut path also produces a `FinalReport.summary`, so existing consumers see the same shape. No downstream contract change.
- **Seeded rules might be unwelcome.** Mitigation: seeded rules are gated behind `seed_builtin_rules_on_first_run` (default true but only when the subsystem is enabled, which defaults false). They are individually deletable from the UI.
- **Bypass concern under the Foundation Guide.** "Chief Orchestrator is the only human-facing ingress." Shortcuts do not bypass the Chief — they pre-decide one of its actions. Chief still owns task records, event emission, approvals, and the final reply. The matcher cannot reach the user directly.

## Affected Files / Modules

New:
- `src/openjarvis/shortcuts/` — new package.
- `tests/shortcuts/`, `tests/integration/shortcuts/` — new test trees.
- `src/openjarvis/server/shortcuts_routes.py` — REST CRUD + `/test`.
- Frontend: new `Shortcuts` view under settings/agent-interact.

Modified:
- `src/openjarvis/agents/orchestrator.py` — add `pre_turn_hook` param to Chief mode; thread through `_chief_loop`.
- `src/openjarvis/cli/serve.py` and managed-agent runtime construction — wire the hook to `openjarvis.shortcuts.try_shortcut` when enabled.
- `src/openjarvis/core/config.py` — add `[shortcuts]` config block.
- `src/openjarvis/tools/_stubs.py` — document `default_post_prompt` in `ToolSpec.metadata`.
- `src/openjarvis/tools/news.py` — set `default_post_prompt` on `get_news` / `get_todays_news`.
- `src/openjarvis/server/__init__.py` (or wherever routers are registered) — mount `shortcuts_routes`.
- DB migration in the existing primary SQLite store — add `shortcut_rules` table.

## User-Visible Behavior Changes

With `config.shortcuts.enabled = false` (default at first release): **no behavior change.**

With `enabled = true` (opt-in, then default in a follow-up release):

- Specific phrases ("what's the news", etc.) return faster, in a narrated voice driven by the configured post-processor model.
- A new **Shortcuts** tab appears in the settings/agent-interact UI.
- Conversation log shows shortcut firings as the matched tool call (same event shape as a normal Chief tool call), plus new `shortcut.*` events visible in the event stream.

## Migration Steps

1. Apply DB migration to add `shortcut_rules` table.
2. Ship code with `config.shortcuts.enabled = false`. No seed runs.
3. Users opt in by setting `enabled = true` in `config.toml`; seeded rules install on next process start when `seed_builtin_rules_on_first_run = true`.
4. In a later release, flip `enabled` default to `true` after live-backend regression passes.

## Rollback Steps

- Set `config.shortcuts.enabled = false`. Chief behavior reverts to today's path; the pre-turn hook short-circuits.
- DB migration is additive; leaving the `shortcut_rules` table in place is harmless. Drop it only on a clean uninstall.
- The `default_post_prompt` keys on `get_news` are inert when the shortcut subsystem is disabled.

## Approval

This notice covers the design in `docs/superpowers/specs/2026-05-27-chat-shortcut-routing-design.md`. User approved sections 1–2 of that design (architecture, data model) in conversation on 2026-05-27 and authorized implementation ("start coding"). Sections 3–5 (matching semantics, events, UI, testing, rollout) are documented in the spec; treat user authorization as covering the spec as a whole. Explicit re-approval is **not** required to begin implementation under this notice, but PRs that diverge materially from the spec must update both this CIN and the spec before merging.
