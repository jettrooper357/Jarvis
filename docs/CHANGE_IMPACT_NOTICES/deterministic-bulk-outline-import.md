# Change Impact Notice: Deterministic Bulk-Outline Import

## What Is Changing

When a user pastes a multi-level project outline (many `Category:` / `Task:` /
`SubTask:` lines, or numbered `N.` / `N.M` / `*` Markdown), the managed-agent
runtime now **imports it deterministically server-side** instead of asking the
model to call `project_import_outline` with the entire outline echoed back as a
tool argument.

The fast path:

1. Detects a bulk outline in the inbound message (`_looks_like_bulk_outline`).
2. Extracts the destination project name from the intro line
   (`_extract_outline_project_name`, e.g. *"add this to the Veridex project"*).
3. Calls the shared `import_outline(store, ...)` core (extracted from the
   `project_import_outline` tool) against the same `ProjectStore` the UI/REST
   API use, with `create_if_missing=true`.
4. Records a synthetic `project_import_outline` tool call for the audit
   log / live event sidebar, and returns the import summary so the **Chief
   still delivers the result** to the user.

It is wired into all three execution paths: `ManagedAgentRuntime._run_chief_turn`,
`ManagedAgentRuntime._run_standard_turn` (channel/delegation/background), and the
streaming chat path `_stream_managed_agent` (the chat UI via
`/v1/chief/messages`).

## Why It Is Needed

The chat UI routes through the Chief Orchestrator (cloud `gpt-4o-mini`,
`max_tokens=1024`). To import a large outline, the prior strategy
(`_prepend_outline_routing_hint`) told the model to emit a single
`project_import_outline` call whose `outline` argument contained the **entire**
paste verbatim — several thousand tokens, far beyond the output budget. The
model could never finish the tool call, the JSON truncated, no tool ran, and
after ~110s of burned turns the chat returned no content ("No response was
generated. Please try again."). The outline is already on the server in the
user message; round-tripping it through the model to get it back is impossible
within budget and pointless.

## Benefits

- Large outlines import reliably and near-instantly (no model round-trip,
  no token-budget ceiling).
- Eliminates the "No response was generated" dead end for this input class.
- One `ProjectStore` write path shared by the tool and the runtime (the tool's
  body was refactored into the reusable `import_outline` function), so both
  stay consistent.

## Risks

- **Wrong project match.** Name extraction is intentionally conservative —
  it scans only the message head for a `to/in/for the <name> project` or
  `project called <name>` phrase. If no clear name is found, the request
  **falls back** to the normal model turn (no behavior change). With
  `create_if_missing=true`, a misspelled name creates a new project rather than
  appending to the intended one — same semantics as the tool itself.
- **Capability gating.** The fast path only fires when the agent's effective
  toolset includes `project_import_outline` (chief / project-manager /
  workflow-manager tier). Other agents are unaffected.
- **Double-create.** `_maybe_materialize_project_task_request` now skips bulk
  outlines, so no stray single top-level task is materialized alongside the
  imported breakdown.

## Affected Files / Modules

Modified:
- `src/openjarvis/tools/project_import_outline.py` — extracted reusable
  `import_outline(store, ...)`; the tool's `execute` now delegates to it.
- `src/openjarvis/server/managed_agent_runtime.py` — added
  `_extract_outline_project_name`, `_maybe_import_bulk_outline`; wired into
  `_run_chief_turn` and `_run_standard_turn`; guarded
  `_maybe_materialize_project_task_request` against bulk outlines.
- `src/openjarvis/server/agent_manager_routes.py` — short-circuit at the start
  of the `_stream_managed_agent` `generate()` generator (the chat path),
  reusing the runtime's `_maybe_import_bulk_outline`.
- `docs/user-guide/project-management.md` — documented the chat fast path.

New tests:
- `tests/server/test_stream_bulk_outline.py` — streaming chat path imports the
  outline without ever calling `stream_full`.
- `tests/server/test_managed_agent_runtime.py` — chief + standard turns import
  deterministically with zero model calls.
- `tests/tools/test_project_tools.py` — `import_outline` tool behavior locked in.

## User-Visible Behavior Changes

- Pasting a multi-level outline into chat now creates the Category/Task/Subtask
  rows and returns a summary, instead of timing out with no reply.
- The conversation/event log shows a single `project_import_outline` tool call
  for the import.
- Non-outline messages, and outlines with no resolvable project name, behave
  exactly as before (normal model turn).

## Migration Steps

None. No schema change; the import writes through the existing `ProjectStore`.

## Rollback Steps

- Remove the `_maybe_import_bulk_outline` call sites in
  `_run_chief_turn`, `_run_standard_turn`, and the `_stream_managed_agent`
  `generate()` generator. The model path (with `_prepend_outline_routing_hint`)
  resumes; the `import_outline` refactor is behavior-preserving and can stay.

## Approval

Additive bug fix on an existing broken flow (no feature removed or degraded);
the Chief remains the only human-facing ingress and the canonical event source.
Authorized by the user in conversation ("Fix the chat failure"). Explicit
re-approval is not required.
