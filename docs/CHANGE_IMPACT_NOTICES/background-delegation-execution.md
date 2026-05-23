# Change Impact Notice: Background Delegation Execution

> **Phase 2F** of `docs/PHASE_2_PLAN.md`. Generated 2026-05-22.
> **Status:** awaiting explicit approval. **No code written.**
>
> Today `managed_agent_assign_task(start_now=True)` runs the subordinate
> *synchronously* — the delegating agent's tool call blocks for the
> entire subordinate turn (`ctx.runtime.run(...)`,
> `managed_agent_tools.py:541`). This notice covers switching that to a
> background execution behind a default-off feature flag.

## What Would Change

Make an immediate-kickoff delegation **enqueue a background execution**
instead of blocking the delegating agent until the subordinate returns.

Four additive layers plus one behavioral change, all behind a
default-off feature flag:

1. **Config flag — `[background_delegation]` in `config.toml`.**
   - `background_delegation.enabled` (default `false`). While false,
     `managed_agent_assign_task` behaves exactly as today — the kickoff
     runs inline via `ctx.runtime.run(...)`.
   - New `BackgroundDelegationConfig` dataclass in `core/config.py`,
     wired into `JarvisConfig` and the TOML loader's `top_sections`
     list (same pattern as `ApprovalGatingConfig` and
     `ChiefIngressConfig`). Plan §2F names a flat
     `background_delegation_enabled`; this notice proposes the
     `[section] enabled` shape for consistency with the two flags
     already shipped.
   - `background_delegation.max_workers` (default `2`) — bound on
     concurrent background subordinate turns.

2. **`BackgroundDelegationExecutor` (additive).**
   - A small bounded worker pool — a `ThreadPoolExecutor(max_workers)`
     wrapped so each job carries the delegation context
     (`agent_id`, `kickoff_message`, `parent_agent_id`,
     `visited_agent_ids`). It mirrors the fire-and-forget daemon-thread
     pattern already used by the Phase-2D approval re-dispatch
     (`agent_manager_routes.py` `_redispatch_after_grant`), but bounded
     and reusable.
   - Each job calls the *existing* `ManagedAgentRuntime.run(...)` — no
     change to the runtime's turn logic. `run()` already persists the
     subordinate's reply via `store_agent_response` and emits the
     `AGENT_TICK_*` / `task.*` events, so a background run is
     UI-visible exactly like a synchronous one.
   - **The scheduler is *not* reused.** `scheduler/` is cron/time-based
     (`TaskScheduler._poll_loop`, `_compute_next_cron`); a delegation
     is "run once, now", a poor fit. A dedicated pool is simpler and
     does not entangle delegation with cron semantics.

3. **`managed_agent_assign_task` wiring (the behavioral change).**
   - When `background_delegation.enabled` is false → unchanged: inline
     `ctx.runtime.run(...)`, result folded into the `ToolResult`
     content as `initial_response` (today's shape).
   - When enabled and `start_now` is truthy → the tool **enqueues** the
     kickoff and returns immediately. The `ToolResult` reports
     `started: true`, `mode: "background"`, the `task_id`, and content
     like `"Delegated to {name} — running in the background as task
     {id}. Its result will return up the chain when it finishes."`
     There is no `initial_response` because the subordinate has not run
     yet.
   - The existing loop/limit guards are preserved and evaluated
     **before** enqueue: the `visited_agent_ids` cycle check
     (`managed_agent_tools.py:527`) and the depth-6 cap (`:531`). A job
     is enqueued only if it would have run synchronously today. The
     `visited` tuple is carried into the background job unchanged so
     the subordinate's own delegations stay bounded.

4. **Task lifecycle on enqueue (additive).**
   - On enqueue the owning `agent_tasks` row moves to `delegated`; when
     a worker picks it up the runtime's existing path moves it to
     `in_progress`; completion lands `completed` / `failed` as today.
     All states are already in the canonical `TaskStatus` enum
     (Phase 2A). No new status string.
   - Events: enqueue emits `task.delegated`; the rest
     (`task.updated` / `task.completed` / `task.failed`,
     `agent.turn.*`) already fire from inside `run()`.

### Open design decision — the upward return path

`AGENTS.md` § "Upward return path is mandatory": a subordinate's result
must roll **back up** to the delegating agent, eventually to the Chief.
When the kickoff was synchronous, the result rode back inside the tool's
`ToolResult`. Background execution breaks that — the tool returns before
the subordinate finishes. How does the result get back up?

- **Option A — events only (simplest).** The background run already
  emits `task.completed` / `task.failed` and stores the subordinate's
  reply. The delegating agent (and the Chief) can observe completion in
  the Inter-Agent Activity sidebar and by calling the existing
  `managed_agent_list_tasks` / message-history tools. **Pro:** zero new
  machinery, fully additive on top of layers 1–4. **Con:** the parent
  is not *actively* told — it must look. For a Chief that delegated and
  then idled, "look later" may never happen on its own.
- **Option B — completion notifies the parent (recommended).** When a
  background job finishes, the executor posts a short completion
  message to the **parent agent's** message log (a `system`/`delegated`
  message: `"Task {id} delegated to {name} finished: {summary}"`),
  mirroring how `_redispatch_after_grant` re-engages an agent. The
  parent picks it up on its next turn; a Chief that delegated several
  tasks naturally reconverges as each reports in. **Pro:** satisfies
  the mandatory upward-return path actively, not passively. **Con:**
  the executor gains a write to the parent's session; if the parent
  should also *re-run* to act on the result, that is extra scope —
  this notice proposes notify-only, no parent re-dispatch.
- **Option C — parent re-dispatch on completion.** As Option B, plus
  re-running the parent agent so it acts on the result immediately.
  **Pro:** fully autonomous reconvergence. **Con:** can cascade runs
  (parent re-runs → may delegate again → …); concurrency and
  cost become hard to reason about. Overlaps with future orchestration
  work — defer.

**Recommendation: Option B**, behind the same
`background_delegation.enabled` flag. It honors the mandatory upward
return path without the cascade risk of Option C. The parent is
*informed*; whether it re-runs stays driven by the existing chat /
tick / Chief loop, unchanged.

## Why It Is Needed

`AGENTS.md` § "Runtime plane" lists **background execution** as an owned
responsibility, and the task model requires delegated work to be
"cancellable" and "resumable when possible" — neither is meaningful
while a delegation monopolises the parent's turn. Today:

- A Chief that delegates three tasks runs them strictly serially, each
  blocking the next, because every `assign_task(start_now=True)` blocks.
- A long subordinate turn freezes the delegating agent (and, for a
  chat-initiated delegation, the user's reply) for its whole duration.
- The `visited_agent_ids` depth-6 cap exists *because* synchronous
  nested delegation would otherwise blow the stack — background
  execution makes deeper, parallel org activity tractable.

This is the gap Phase 2F was scheduled to close. It is filed as a CIN
because it changes the observable behavior of an existing tool
(`AGENTS.md` § "Forbidden behaviors": never silently degrade a tool).

## Benefits

- **Parallel delegation.** A Chief can fan work out to several
  subordinates that run concurrently (bounded by `max_workers`).
- **Non-blocking parent turns.** The delegating agent — and a
  chat-initiated user reply — return promptly instead of waiting out
  the whole subordinate turn.
- **Honors the runtime-plane contract.** Background execution becomes a
  real capability, not a synonym for "serial".
- **No impact when off.** With `background_delegation.enabled = false`
  (default), `managed_agent_assign_task` is byte-identical to today,
  `initial_response` included.
- **Reuses proven machinery.** The job body is the unchanged
  `ManagedAgentRuntime.run(...)`; only *where* it runs changes.

## Risks

| Risk | Severity | Mitigation |
|---|---|---|
| The delegating agent loses the inline `initial_response` and never learns the outcome | **High** | Option B posts a completion message back to the parent's log; `task.completed`/`task.failed` events surface in the activity sidebar. With the flag off, `initial_response` is preserved exactly. |
| A background job is lost on server shutdown / crash mid-run | Medium | The queue is in-memory in this CIN (durable queue deferred). On shutdown the executor drains briefly, then logs abandoned jobs; the owning task stays in `delegated`/`in_progress` and is visible + re-runnable. No silent data loss — flagged, not hidden. |
| Unbounded concurrency exhausts CPU / model-engine capacity | Medium | `max_workers` (default 2) bounds concurrent turns; excess jobs queue. The single local inference engine already serialises model calls, so the realistic ceiling is small. |
| A background subordinate error becomes invisible | Medium | `run()` already emits `task.failed` and stores an error response; Option B's completion message reports failures too. The executor logs any exception escaping `run()`. |
| Concurrent workers writing the SQLite manager/approval/trace stores race | Medium | Verify connection-per-thread / WAL before enabling. If the stores are not thread-safe, serialise store writes or use a connection pool — this is a **stage-1 verification gate**, not an assumption. |
| Tests asserting on the synchronous `initial_response` shape break | Low | Flag defaults **off** → existing tests unaffected. New tests opt into the flag explicitly. |
| Delegation loops / runaway depth in background | Low | The `visited_agent_ids` cycle check and depth-6 cap are evaluated before enqueue and the `visited` tuple is carried into the job — identical bounding to the synchronous path. |
| Cancellation of an enqueued-but-not-started job | Low | A job still in the queue can be dropped when its task is cancelled; an in-flight turn runs to completion (cooperative cancellation of a running turn is out of scope — deferred to a later phase, documented as a limitation). |

## Side Effects

- **`agent_tasks` rows pass through `delegated` then `in_progress`**
  for background kickoffs; both are existing canonical states.
- **`task.delegated` event volume rises** for immediate-kickoff
  delegations (today an immediate kickoff goes straight to a run).
- **The parent agent's message log gains completion messages** under
  Option B — one short `delegated`-mode message per finished
  background task.
- **A daemon worker pool exists for the server's lifetime** when the
  flag is on — `max_workers` idle threads. Negligible footprint.

## Migration Path

Three stages, all behind `background_delegation.enabled` (default false):

1. **Stage 1 — config + executor + tool wiring (server, flag off).**
   - `BackgroundDelegationConfig` (`enabled`, `max_workers`) + TOML
     wiring.
   - `BackgroundDelegationExecutor` — bounded pool, context-carrying
     jobs, exception logging, brief shutdown drain.
   - `managed_agent_assign_task` switches to enqueue when the flag is
     on; loop/depth guards evaluated before enqueue; `ToolResult` shape
     for the background path.
   - **Verification gate:** confirm the SQLite stores are safe under
     concurrent worker writes; serialise if not.
   - Tests: flag off = inline run, `initial_response` preserved; flag
     on = enqueue, tool returns immediately with `mode: "background"`;
     enqueued job runs and stores the subordinate reply; loop + depth
     guards still block before enqueue; `max_workers` bounds
     concurrency.

2. **Stage 2 — upward return path (Option B).**
   - Background-job completion posts a completion/failure message to
     the parent agent's log.
   - Tests: completion message reaches the parent; failure path
     reported; activity-sidebar events present (no new UI expected —
     the Inter-Agent Activity panel already renders `task.*` events).

3. **Stage 3 — opt-in docs, flag stays off.**
   - `docs/user-guide/agents.md` — background delegation section.
   - `docs/architecture/overview.md` — note background execution in the
     runtime plane / event table.
   - `CHANGELOG.md` entry.
   - `docs/AUGMENTED_FEATURES.md` — mark background delegation
     protected once shipped.
   - **The flag is NOT flipped on by default.** Background delegation
     changes an existing tool's observable behavior; it is an opt-in
     posture an admin chooses per deployment.

## Rollback Path

- **Stage 3:** revert docs. No code impact.
- **Stage 2:** revert the completion-notification write; the executor
  from stage 1 still runs jobs (Option-A mode — events only).
- **Stage 1:** set `background_delegation.enabled = false` (or revert
  the stage). `managed_agent_assign_task` returns to inline synchronous
  execution immediately.

No schema changes, no destructive data operations at any stage.

## Exact Files Affected

Server (stage 1):
- `src/openjarvis/core/config.py` — `BackgroundDelegationConfig`;
  `top_sections`.
- `src/openjarvis/server/managed_agent_runtime.py` (or a new
  `src/openjarvis/server/background_delegation.py`) —
  `BackgroundDelegationExecutor`.
- `src/openjarvis/tools/managed_agent_tools.py` —
  `ManagedAgentAssignTaskTool.execute` enqueue branch.
- `tests/server/test_phase2f_background_delegation.py` — new.

Server (stage 2):
- `src/openjarvis/server/background_delegation.py` — completion
  callback posting to the parent's message log.
- `tests/server/test_phase2f_background_delegation.py` — extended.

Documentation (stage 3):
- `docs/user-guide/agents.md`
- `docs/architecture/overview.md`
- `CHANGELOG.md`
- `docs/AUGMENTED_FEATURES.md`

No frontend files: the Inter-Agent Activity sidebar already renders the
`task.*` events the background path emits.

## Reversibility

**Fully reversible.** No schema change — the executor and the enqueue
branch are pure additions, gated by a default-off flag. With
`background_delegation.enabled = false`, `managed_agent_assign_task` is
byte-identical to its current behavior. No tool, route, or event is
removed or renamed.

## Approval Question

Do you approve implementing this change as three stages, with:

- the executor and enqueue path behind `background_delegation.enabled`
  (**default off**, and **kept off** — opt-in, not a default behavior
  change),
- a **dedicated bounded worker pool** (not the cron scheduler) as the
  executor, and
- **Option B** (background completion notifies the parent agent, but
  does **not** re-dispatch it) as the upward return path?

If yes, I will build stage 1, stop and report, then stage 2, stop and
report, then stage 3. If you prefer **Option A** (events only, no
parent notification — fully additive, but the parent must look),
**Option C** (notify *and* re-dispatch the parent), or want a durable
on-disk job queue in scope rather than the in-memory one, say so before
I start.
