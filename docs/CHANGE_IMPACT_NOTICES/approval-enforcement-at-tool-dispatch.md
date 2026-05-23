# Change Impact Notice: Approval Enforcement at Tool Dispatch

> **Phase 2D (enforcement half)** of `docs/PHASE_2_PLAN.md`. Generated
> 2026-05-22.
> **Status:** awaiting explicit approval. **No code written.**
>
> The approval *data plane* — `ApprovalStore`, the `agent_approvals`
> table, `GET/POST /v1/approvals`, and the `approval.requested` /
> `approval.resolved` events — shipped additively in Phase 2D and is
> currently **dormant**: nothing creates an approval request, because no
> code path consults the `requires_approval_*` capability axes at tool
> dispatch. This notice covers wiring that last link.

## What Would Change

Make a tool call **block on human approval** when the tool is listed in
the owning agent's `requires_approval_tools` capability axis.

Five additive layers plus one behavioral change, all behind a
default-off feature flag:

1. **Config flag — `[approval_gating]` in `config.toml`.**
   - `approval_gating.enabled` (default `false`). While false, tool
     dispatch behaves exactly as today — no gate, no approval rows.
   - New `ApprovalGatingConfig` dataclass in `core/config.py`, wired
     into `JarvisConfig` and the TOML loader's `top_sections` list
     (same pattern as `ChiefIngressConfig`).

2. **Single-use approval semantics — additive column on `agent_approvals`.**
   - Add nullable `consumed_at REAL` and `args_hash TEXT`.
   - A *granted* approval authorizes exactly one execution of a
     specific `(agent_id, capability, args_hash)` triple. Once the gate
     consumes it, `consumed_at` is set and the approval can't authorize
     another call. This keeps the gate deny-by-default: a stale grant
     can't be replayed.
   - `args_hash` is a stable SHA-256 of the normalized tool arguments,
     so "approve `delete_files(/tmp/x)`" does not also authorize
     `delete_files(/etc)`.

3. **`ApprovalStore` helpers (additive).**
   - `find_actionable(agent_id, capability, args_hash)` — returns the
     newest unconsumed `granted` or any `denied` approval matching the
     triple, or `None`.
   - `mark_consumed(approval_id)` — sets `consumed_at`.

4. **The gate — a dispatch interceptor in the managed-agent runtime.**
   The runtime already wraps `agent._executor.execute` to record tool
   calls (`_tracked_execute`, `managed_agent_runtime.py:1208`; the chief
   variant at `:1266`). A shared `_approval_gated_execute` wrapper is
   inserted *inside* that existing wrap, so every managed-agent tool
   call passes through it. Per call:
   - If `approval_gating.enabled` is false → run normally (today's
     behavior).
   - If the tool is **not** in the agent's `requires_approval_tools`
     axis → run normally.
   - If it **is** gated, compute `args_hash` and call
     `find_actionable`:
     - **Granted + unconsumed** → `mark_consumed`, run the tool.
     - **Denied** → return a failed `ToolResult` whose content is the
       denial reason. The agent sees the refusal and adapts.
     - **None** → create a pending `ApprovalRequest` via
       `ApprovalStore.request()`; set the owning `agent_tasks` row to
       `requires_approval = 1` and status `awaiting_approval`; return a
       `ToolResult` with `success = False` and content
       `"Awaiting human approval — request {id}. This action is paused
       until a human grants it."`. The agent turn finishes normally,
       reporting that it is blocked.

5. **`GET /v1/approvals` UI surfacing (additive, frontend).**
   - The Phase-2D approval data plane gets a UI: pending approvals
     render in the `InterAgentActivityPanel` sidebar and as a CTA card
     on the agent detail Overview, extending the existing
     `ChiefPendingCard` pattern. Grant/Deny buttons call the existing
     `/v1/approvals/{id}/grant|deny` endpoints.

6. **The one behavioral change — resume after grant.**
   Granting an approval (`POST /v1/approvals/{id}/grant`) optionally
   **re-runs the blocked agent** so the user doesn't have to re-send
   their message. See "Open design decision" below — this is the only
   part that is not purely additive, and the reason this notice is
   required.

### Open design decision — resume behavior

When a human grants a pending approval, what happens next?

- **Option A — no auto-resume (simplest).** The grant just records the
  decision. The next time the agent runs (user re-sends, scheduler
  fires, or the user clicks "retry" on the CTA card), the gate finds
  the granted approval and proceeds. **Pro:** zero turn-lifecycle
  coupling, fully additive. **Con:** clunky — the user must re-trigger.
- **Option B — auto-resume on grant (recommended).** The grant handler
  re-dispatches the original user message to the agent. The agent
  re-plans with the approval now available; the gate consumes the
  grant when the same tool call recurs. **Pro:** seamless UX. **Con:**
  the grant endpoint gains a side effect (it triggers an agent run),
  and re-planning means the agent *might* not re-issue the identical
  call — acceptable, arguably more correct, but a behavior change.
- **Option C — checkpoint-and-replay.** Persist a turn checkpoint at
  the gate, restore and replay exactly on grant. **Pro:** exact
  resumption. **Con:** significant coupling to the turn lifecycle and
  the `agent_checkpoints` table; overlaps heavily with Phase 2F/2G.

**Recommendation: Option B**, behind the same `approval_gating.enabled`
flag. Option C is deferred — it belongs with the 2F/2G resumable-
execution work and should not be rushed in here.

## Why It Is Needed

`AGENTS.md` § "Security and approvals":

> "Any action that can: modify files, run shell/system commands, access
> remote services, change agent hierarchy, alter capability policy,
> delete data, mutate schemas, disable protections — must be explicitly
> governed by approvals, policy, or both."

Today nothing enforces this. An agent with `delete_files` or a
shell-capable tool runs it unconditionally. The `requires_approval_*`
axes exist (Phase 2A) and the approval store exists (Phase 2D), but the
two are not connected — the safety mechanism is built and inert.

## Benefits

- **Closes the headline security gap.** Dangerous capabilities become
  genuinely gated, not just tagged.
- **Completes Phase 2D.** Turns the dormant approval data plane into a
  working feature; the `approval.requested` / `approval.resolved`
  events finally have a producer.
- **Deny-by-default and least-privilege.** Single-use, args-scoped
  grants mean an approval authorizes exactly one specific action.
- **No impact when off.** With `approval_gating.enabled = false`
  (default), tool dispatch is byte-identical to today.
- **Per-agent, per-capability granularity.** An agent only gates the
  tools an admin explicitly lists in `config.requires_approval_tools`;
  everything else runs freely.

## Risks

| Risk | Severity | Mitigation |
|---|---|---|
| A gated agent stalls forever waiting on a human who never responds | **High** | The turn does *not* block — it finishes and reports "awaiting approval". The task sits in `awaiting_approval`; an admin sees it in the sidebar/CTA. Optional `approval_gating.timeout_seconds` auto-denies stale requests (default 0 = no timeout). |
| Grant endpoint gaining a side effect (Option B re-run) surprises API consumers | Medium | Re-run only fires when `approval_gating.enabled` is true. The grant response shape is unchanged; the re-run is a fire-and-forget background dispatch, mirroring the existing immediate-tick pattern. |
| `args_hash` mismatch — agent re-issues a *slightly* different call after grant, gate creates a second request | Medium | Hash is over *normalized* args (sorted keys, trimmed whitespace). Documented behavior: a materially different call legitimately needs its own approval. The CTA card shows the exact args so the human knows what they approved. |
| Approval bypass via a non-managed code path (CLI `jarvis ask`, direct SDK) | Medium | This notice scopes the gate to the **managed-agent runtime** only. CLI/SDK direct tool use is out of scope and explicitly documented as ungated. A follow-up can extend the gate to `ToolExecutor` itself if desired — flagged, not silently skipped. |
| Self-approval — an agent grants its own pending request via the `/v1/approvals` API (it has HTTP tools) | Medium | Grant/deny require a human-facing call. As a hardening step this notice adds an `approval_gating.require_human_grant` check that rejects grants whose `resolved_by` is an agent id. Default on. |
| Gate adds latency to every tool call when enabled | Low | The gate is one in-memory set membership test (`requires_approval_tools`) plus, only for gated tools, one indexed SQLite lookup. Negligible. |
| Existing tests that run gated tools start failing if the flag defaults on | Low | Flag defaults **off**. Existing behavior unchanged. New tests opt in explicitly. |

## Side Effects

- **`agent_approvals` row volume grows** when gating is enabled — one
  row per gated tool invocation. Append-only; no cleanup TTL in this
  change (defer).
- **`agent_tasks` rows transition through `awaiting_approval`** more
  often. The canonical `TaskStatus` enum already includes this state
  (Phase 2A); the legacy mapper renders it as `active`.
- **`approval.requested` / `approval.resolved` event volume rises from
  zero.** Subscribers ignore event types they don't handle.
- **Frontend `InterAgentActivityPanel` gains approval entries** — this
  is the B2 UI gap from the "what remains undone" review, folded in
  here so the feature is usable end-to-end.

## Migration Path

Three stages, all behind `approval_gating.enabled` (default false):

1. **Stage 1 — schema + store + gate (server, flag off).**
   - ALTER TABLE `agent_approvals` ADD `consumed_at`, `args_hash`
     (nullable, additive).
   - `ApprovalGatingConfig` + TOML wiring.
   - `find_actionable` / `mark_consumed` on `ApprovalStore`.
   - `_approval_gated_execute` wrapper in `managed_agent_runtime.py`.
   - Tests: gate off = no-op; gate on + no policy = no-op; gate on +
     gated tool + no approval = pending row created + task
     `awaiting_approval`; granted = runs once then consumed; denied =
     failed result; args-hash scoping; self-grant rejection.

2. **Stage 2 — resume + UI (Option B + frontend).**
   - Grant handler re-dispatches the blocked agent.
   - `InterAgentActivityPanel` + Overview CTA render pending approvals;
     Grant/Deny wired to existing endpoints.
   - Tests: grant triggers re-run; UI render tests.

3. **Stage 3 — opt-in docs, flag stays off.**
   - New `docs/user-guide/approvals.md`.
   - `docs/architecture/overview.md` event table updated.
   - `CHANGELOG.md` entry.
   - **The flag is NOT flipped on by default.** Approval gating is an
     opt-in security posture an admin chooses per deployment, not a
     default behavior change. (This differs from Phase 2E, where the
     Chief-ingress flag was flipped — there the feature degrades
     gracefully; here, flipping it on changes whether tools run.)

## Rollback Path

- **Stage 3:** revert docs. No code impact.
- **Stage 2:** revert the grant-handler re-run and the UI changes; the
  gate from stage 1 still works in Option-A mode (no auto-resume).
- **Stage 1:** set `approval_gating.enabled = false` (or revert the
  stage's changes). The two new `agent_approvals` columns are nullable and
  unread when the flag is off — safe to leave or drop.

No destructive data operations at any stage.

## Exact Files Affected

Server (stage 1):
- `src/openjarvis/core/config.py` — `ApprovalGatingConfig`; `top_sections`.
- `src/openjarvis/agents/approvals.py` — `consumed_at` + `args_hash`
  columns; `find_actionable`, `mark_consumed`; arg-normalization hash
  helper.
- `src/openjarvis/server/managed_agent_runtime.py` —
  `_approval_gated_execute` wrapper inserted into the existing
  `_executor.execute` wrap points.
- `tests/agents/test_phase2d_approval_enforcement.py` — new.

Server (stage 2):
- `src/openjarvis/server/agent_manager_routes.py` — grant handler
  re-dispatch (Option B).

Frontend (stage 2):
- `frontend/src/lib/api.ts` — `listApprovals`, `grantApproval`,
  `denyApproval`.
- `frontend/src/pages/AgentsPage.tsx` — approval entries in
  `InterAgentActivityPanel`; Overview CTA card.
- `tests` — frontend render tests (closes the B4 gap for this surface).

Documentation (stage 3):
- `docs/user-guide/approvals.md` (new)
- `docs/architecture/overview.md`
- `CHANGELOG.md`
- `docs/AUGMENTED_FEATURES.md` — mark the gate protected once shipped.

## Reversibility

**Fully reversible.** The two new `agent_approvals` columns are
nullable and unread while the flag is off. The gate is a wrapper that
is a transparent pass-through when `approval_gating.enabled` is false.
No endpoint is removed, no schema renamed, no row deleted. Disabling
the flag restores byte-identical pre-change tool dispatch.

## Approval Question

Do you approve implementing this change as three stages, with:

- the gate and resume behind `approval_gating.enabled` (**default
  off**, and **kept off** — this is an opt-in security posture, not a
  default behavior change), and
- **Option B** (auto-resume on grant) as the resume mechanism?

If yes, I will build stage 1, stop and report, then stage 2, stop and
report, then stage 3. If you prefer **Option A** (no auto-resume,
fully additive, clunkier UX), or want the gate extended to the CLI/SDK
`ToolExecutor` path in scope, say so before I start.
