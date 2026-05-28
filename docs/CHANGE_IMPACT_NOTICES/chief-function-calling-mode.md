# Change Impact Notice: Chief Function-Calling Mode

## What Would Change

The Chief Orchestrator currently runs in `orchestrator_mode = "chief"`, which is a hand-rolled structured-JSON protocol. The model is asked to emit:

```json
{"action": "complete|delegate|execute_direct|ask_user|fail", "reason": "...", ...}
```

Most OpenAI / OpenAI-compatible models (gpt-4o-mini, gpt-4o, the Anthropic/Bedrock-on-OpenAI shims, etc.) are heavily trained to emit OpenAI function-calling output (the `tool_calls` field) and **systematically ignore** the chief's bespoke schema. In production this produces a tight failure mode:

1. Model emits `{"name": "get_news", "arguments": {...}}` as plain content.
2. `parse_action` raises `ParseError`.
3. The chief retries with a repair turn; the model produces the same shape.
4. The chief gives up after `max_turns` (default 8) and returns the raw content as fallback text.

One chief reply takes 200–400s and renders as `{"name": "...", "arguments": ...}` JSON in the chat. Reproduced today on the live backend.

This CIN proposes a second chief mode, `orchestrator_mode = "function_calling"`, that uses the existing `_run_function_calling` loop in `openjarvis.agents.orchestrator.OrchestratorAgent`. Tools are passed natively as OpenAI function specs; the model's `tool_calls` field is dispatched directly through the existing `ToolExecutor`. The bespoke `parse_action` JSON is removed from the hot path for this mode.

### Action mapping (chief mode → function calling mode)

| Chief action | Function-calling equivalent |
|---|---|
| `delegate` | Call existing tool `managed_agent_delegate` (already auto-injected via `AUTO_COLLABORATION_TOOLS`) |
| `execute_direct` | Just call the tool. This is the entire point of function-calling. |
| `complete` | Model emits no more `tool_calls`; final assistant message becomes the chief's reply. |
| `fail` | Same as `complete` — the assistant message says what failed. No special path needed. |
| `ask_user` | **New tool** `chief_ask_user(question, reason?, options?, expected_response_type?)`. Persists a checkpoint and parks the agent in `input_required` status, matching the current `/chief-pending` and `/chief-resume` routes byte-for-byte. |

### Feature flag

`config.chief_function_calling.enabled` defaults to **false**. The new mode is opted-in per-agent via `agent.config.orchestrator_mode = "function_calling"`. The existing chief mode remains the default and the fallback.

## Why It Is Needed

- The current chief mode is **unreliable** on every commercially relevant model in the cloud engine. The user has reproduced the failure repeatedly. The system has been ostensibly working only because the model occasionally guesses the right JSON shape; on a hard tool-call ask ("what is the news") it fails deterministically.
- gpt-4o-mini is the cheapest mainstream model and the fastest. The current bug makes Jarvis appear slow and broken when it is neither. Switching modes restores ~5s latency for a single tool call.
- Function calling is the industry-standard protocol. Building on it future-proofs the chief against model upgrades and reduces the per-model prompt-engineering cost to zero.
- No new persistence or routing changes are needed. The chief's role as canonical ingress (Phase 2E) is preserved.

## Benefits

- Reliable tool dispatch with any function-calling-capable model.
- Latency drops from 200–400s back to single-call timing (~5–30s).
- Removes the chief-specific parser as a load-bearing component for the function-calling chief.
- `ask_user` becomes a first-class explicit tool the model can choose, rather than an action wrapper the parser has to recognize.
- `parse_action` and `chief_prompt.py` remain for backward compatibility and for non-function-calling models (e.g., older local models without OpenAI tool-calling support).

## Risks

- **Chief's structured `final_report` shape disappears** from the function-calling mode. Today nothing downstream consumes it, but if a future component relies on `final_report.status` or `final_report.summary` specifically, the function-calling chief will not emit those fields.
- **`ask_user` checkpoint semantics** must be preserved exactly. The current `/chief-pending` and `/chief-resume` routes read `tool_state` from `agent_checkpoints` with fields `{question, run_id, turns}`. The new `chief_ask_user` tool must write the same shape or the existing UI breaks.
- **`already_delegated` guard** in `_chief_loop` (prevents `execute_direct` after a `delegate` to avoid the "two Iron Saints tasks" bug) needs a function-calling equivalent. Proposed: a per-run `_delegation_count` budget on the orchestrator that caps delegation tool calls per run.
- Behavior under loop / depth guards already lives on `managed_agent_assign_task` itself; that path is unchanged.
- Tool approval gating (Phase 2D) already runs at tool dispatch in `managed_agent_runtime`; that path is unchanged.

## Side Effects

- New tool `chief_ask_user` (registered via `ToolRegistry`, gated to chief-role agents via the same allowlist that gates other meta-tools).
- New config block `[chief_function_calling]` in `JarvisConfig` (single field: `enabled: bool = False`).
- New optional value `"function_calling"` for `agent.config.orchestrator_mode`.
- `OrchestratorAgent.__init__` already accepts `mode = "chief" | "function_calling" | "structured"`; no changes needed there.
- Agent Overview should display the active orchestrator mode in the Capability Inspector. Additive.
- New events emitted: none. Existing `tool.started` / `tool.finished` / `task.*` / `approval.*` events continue to fire from the underlying tool dispatch path.

## Migration Path

1. Land the CIN (this file).
2. Implement `chief_ask_user` tool with checkpoint write that matches existing `/chief-pending` / `/chief-resume` payload shape.
3. Add `[chief_function_calling]` config block (default disabled).
4. Wire `_run_chief_turn` in `managed_agent_runtime` to inspect `agent.config.orchestrator_mode` and route to `_run_function_calling` when set to `"function_calling"` AND the flag is on; otherwise stay on `_run_chief`.
5. Add tests:
   - `chief_ask_user` writes the checkpoint shape `/chief-pending` and `/chief-resume` already consume.
   - Function-calling chief dispatches a `get_news` call end-to-end.
   - `already_delegated` parity — a single function-calling chief turn cannot delegate twice.
   - Backwards compat: when flag off, chief behavior is byte-identical to today.
6. Update `docs/architecture/overview.md` and `docs/user-guide/agents.md`.
7. Default the flag off; flip per-agent only after verification on the user's Chief.

## Rollback Path

- Flip `[chief_function_calling].enabled` to `false`. All chiefs revert to current behavior.
- Per-agent rollback: set `agent.config.orchestrator_mode = "chief"`.
- The `chief_ask_user` tool stays registered but unused; harmless.
- No data shape changes; no migration to undo.

## Exact Files Affected

Backend:
- `src/openjarvis/core/config.py` — new `ChiefFunctionCallingConfig` dataclass + top-level binding.
- `src/openjarvis/tools/chief_ask_user.py` — new tool implementation.
- `src/openjarvis/tools/__init__.py` — import hook for the new tool.
- `src/openjarvis/server/managed_agent_runtime.py` — `_run_chief_turn` routes by `orchestrator_mode` + flag.
- `src/openjarvis/agents/capabilities.py` — auto-inject `chief_ask_user` for chief-role agents.

Frontend:
- `frontend/src/pages/AgentsPage.tsx` — surface `orchestrator_mode` in the Capability Inspector (read-only display in first pass).

Tests:
- `tests/agents/test_chief_function_calling_mode.py` — new.
- `tests/tools/test_chief_ask_user.py` — new.
- `tests/server/test_chief_pending_routes.py` — add parity test for the new tool's checkpoint payload.

Docs:
- `docs/architecture/overview.md`, `docs/user-guide/agents.md`, `docs/AUGMENTED_FEATURES.md`, `docs/FEATURE_PRESERVATION_MATRIX.md`, `docs/PHASE_2_PLAN.md` post-Phase-2 section.

## Reversibility

Fully reversible via the feature flag and `agent.config.orchestrator_mode` per-agent. No schema migrations, no destructive changes.

## Approval Question

Approve implementing this change as an additive, feature-flagged second chief mode (`orchestrator_mode = "function_calling"`) with:

- a new `chief_ask_user` tool that preserves the existing `/chief-pending` / `/chief-resume` checkpoint shape,
- `[chief_function_calling].enabled` config flag default false,
- per-agent opt-in via `agent.config.orchestrator_mode`,
- the existing chief mode unchanged and remaining the default,
- tests for `chief_ask_user`, end-to-end function-calling dispatch, the no-double-delegate guard, and flag-off byte-identical behavior?
