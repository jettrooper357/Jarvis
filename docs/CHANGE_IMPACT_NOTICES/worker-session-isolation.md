# Change Impact Notice: Worker Session Isolation

> **Phase 2G** of `docs/PHASE_2_PLAN.md`. Generated 2026-05-22.
> **Status:** awaiting explicit approval. **No code written.**
>
> Today, every managed agent has a single conversation log
> (`agent_messages` filtered by `agent_id`). A delegated turn against a
> Worker agent sees *all* of that agent's prior messages, including
> unrelated prior delegations and direct chat — cross-task context
> bleeds in. The 2A migration added an unused `agent_tasks.task_session_id`
> column reserved for exactly this work; this notice covers wiring it.
>
> Depends on Phase 2F's upward-return path (the parent notification on
> completion) so isolation does not break the chain of command.

## What Would Change

Give each delegated task its **own scoped session inside the worker's
message log**, so a delegated turn runs against a clean, per-task
slice instead of the worker's full history.

Five additive layers plus one behavioral change, all behind a
default-off feature flag:

1. **Config flag — `[worker_session_isolation]` in `config.toml`.**
   - `worker_session_isolation.enabled` (default `false`). While
     false, the message-loader and writers behave exactly as today —
     untagged read/write against the full per-agent log.
   - New `WorkerSessionIsolationConfig` dataclass in `core/config.py`,
     wired into `JarvisConfig` and the TOML `top_sections` list (same
     pattern as `ApprovalGatingConfig` and `BackgroundDelegationConfig`).

2. **Schema — additive nullable column on `agent_messages`.**
   - `ALTER TABLE agent_messages ADD COLUMN session_id TEXT` (nullable,
     additive). Existing rows continue to read with `session_id = NULL`,
     which the loader treats as "general session".
   - The `agent_tasks.task_session_id` column already exists (2A); the
     2G runtime starts populating it when isolation is on.

3. **`AgentManager` helpers — session-aware (additive).**
   - `send_message(agent_id, content, mode, *, session_id=None)` —
     persists the optional scope.
   - `store_agent_response(agent_id, content, tool_calls, *, session_id=None)`
     — same.
   - `list_messages(agent_id, limit, *, session_id=None)` — when a
     non-empty `session_id` is passed, filters by it; when omitted or
     empty, returns *only untagged* rows by default. **Behavior change
     gate:** the untagged-only filter is itself flag-gated, so flag-off
     callers see today's exact result set (all rows).
   - The flag-gated reader semantics are the only non-additive change
     in this layer — see "Open design decision" below.

4. **Runtime threading — session-aware ``ManagedAgentRuntime.run``.**
   The runtime already loads the agent's recent messages to build
   conversation history. When running a task whose
   `task_session_id` is non-empty AND the flag is on:
   - the history loader filters by that session id;
   - the kickoff message and the agent's reply are written with that
     session id;
   - tool-call records inherit the session id via the runtime's existing
     trace/message writers.
   When the task has no `task_session_id` (legacy or untagged) OR the
   flag is off, the runtime is byte-identical to today.

5. **Tool wiring — mint a session at delegation time.**
   `managed_agent_assign_task` and `managed_agent_delegate` mint a
   fresh `session_id` when:
   - the flag is on, **and**
   - they create the task (assign_task) or build a delegated turn
     (delegate).
   They write it to `agent_tasks.task_session_id` (assign_task) or
   propagate it to the in-flight `runtime.run(...)` call (delegate),
   and emit `AGENT_SESSION_FORKED`. The Phase 2F
   background-execution path carries the session id through the
   executor unchanged.

6. **Event types — new lifecycle signals.**
   - `EventType.AGENT_SESSION_FORKED` — a delegation minted a new
     scoped session for the worker (payload: `parent_agent_id`,
     `worker_agent_id`, `task_id`, `session_id`).
   - `EventType.AGENT_SESSION_MERGED` — the per-task session ended
     and its summary was rolled back up. Reuses the Phase 2F
     parent-notification write as the merge act; the event fires on
     that write.

### Open design decision — history-loader semantics

When the flag is on, what does `list_messages(agent_id)` (no
session_id) return?

- **Option A — "untagged only" (recommended).** The loader returns
  only rows where `session_id IS NULL OR session_id = ''`. Delegated
  turns explicitly pass their `task_session_id`. **Pro:** clean
  isolation — a delegated turn never sees the general log, and the
  general log never sees per-task chatter. **Con:** a follow-up
  delegation that wants context from a prior delegation must opt in
  by passing the prior `session_id`.
- **Option B — "merged view" (most additive).** The loader returns
  *all* rows for the agent regardless of session id when no
  `session_id` is requested. Delegated turns still filter. **Pro:**
  every existing caller is byte-identical. **Con:** the worker's
  general log accretes per-task chatter — isolation is one-way
  (delegated turn doesn't see general, general sees delegated). The
  per-agent log effectively becomes the audit trail and isolation is
  reduced to "the delegated turn sees a clean slice".
- **Option C — seed the child from the parent.** As Option A, plus
  the delegation copies a short context summary from the parent's log
  into the child's session at fork time. **Pro:** the worker has
  context the parent intended it to have. **Con:** what to copy is a
  judgment call (a summary requires an LLM call, raw copy may leak
  credentials — must route through the existing
  `CredentialScrubber`); adds dependencies. Defer.

**Recommendation: Option A**, behind the same
`worker_session_isolation.enabled` flag. The 2F upward-return notice
already provides the rolled-up summary at completion, so the parent
side has a record without needing a seeded child. A future Phase
can add Option C as an opt-in seeding strategy.

## Why It Is Needed

`AGENTS.md` § "Session and memory rules":

> "Worker sessions must be linkable to their parent task and parent
> agent. Session isolation is required for long-running or parallel
> subordinate work."

Today a Worker is conversationally a single bucket. Delegated turn N+1
sees turn N's residue and any unrelated direct chat. Combined with
Phase 2F (which makes parallel delegation real), the bleed becomes a
correctness issue rather than a mild annoyance: a Worker handling two
concurrent background tasks would interleave their context.

This is the gap Phase 2G was scheduled to close. It is filed as a CIN
because it changes the observable behavior of
`managed_agent_delegate` / `managed_agent_assign_task` (the
subordinate sees a different message list) and, under Option A, the
behavior of `AgentManager.list_messages` (untagged-only when the flag
is on).

## Benefits

- **Clean per-task context.** A delegated turn sees only the messages
  scoped to its task, not the worker's full history.
- **Parallel-safe.** Two concurrent background delegations against
  the same worker no longer interleave their context.
- **Honors the session-isolation contract.** The mandatory
  "linkable to parent task / parent agent" requirement becomes real.
- **No impact when off.** With
  `worker_session_isolation.enabled = false` (default), the runtime
  and message log are byte-identical to today.
- **Pairs cleanly with 2F.** 2F gives the worker non-blocking,
  parallel kickoffs; 2G makes those kickoffs context-clean. The 2F
  parent-notification doubles as the merge.
- **Audit unchanged.** All rows persist append-only with `session_id`
  metadata — nothing is deleted, the full transcript stays inspectable.

## Risks

| Risk | Severity | Mitigation |
|---|---|---|
| A Worker that relied on cross-task memory loses it during delegated turns | **High** | Flag defaults **off**. When on, opt-in seeding (Option C) can be added later. Document the trade-off in `docs/user-guide/agents.md`. |
| The flag-gated `list_messages` untagged-only filter breaks frontend / UI consumers that read all rows | **High** | The Activity sidebar and per-agent message view read `list_messages` without a `session_id`. Plan: the UI explicitly requests "all rows" (a new `include_all_sessions=True`) for the audit view; the runtime-internal loader passes the task's `session_id`. Stage 1 includes this UI parameter so the change does not regress the audit surface. |
| `agent_messages` row volume rises modestly | Low | One nullable column; existing rows unaffected; no index added (filtering uses the existing `agent_id` lookup + WHERE on `session_id`). |
| Tagged rows accumulate forever once a task ends | Medium | Append-only by design (audit). No cleanup TTL in this change — defer. The `agent_tasks` row remains the index. |
| Phase 2F background jobs lose the session id at the worker-pool hand-off | Medium | The executor's job already carries `agent_id` and `parent_agent_id`; add `task_session_id` to the submit signature. Covered in stage 2 tests. |
| Delegation seeding (if Option C is later adopted) leaks credentials into the child | Medium (future) | Any copy must route through the existing `CredentialScrubber`. Option C is explicitly **deferred** in this CIN. |
| Cross-store consistency — a `task_session_id` is written but no message ever uses it | Low | Acceptable: the task carries the scope even if the kickoff didn't generate messages. The reader returns an empty slice; the runtime treats it as a fresh session. |
| Existing tests that assert on `list_messages(agent_id)` returning every row break | Low | Flag defaults off — unaffected. Flag-on tests pass `include_all_sessions=True` or a specific `session_id`. |

## Side Effects

- **`agent_messages.session_id` column exists** after migration, even
  with the flag off. Nullable, additive, unread.
- **`AGENT_SESSION_FORKED` / `AGENT_SESSION_MERGED` events** appear on
  the bus when the flag is on. Subscribers ignore event types they
  don't handle.
- **Inter-Agent Activity sidebar** may surface session fork/merge
  signals once subscribed; not required for this notice's MVP.
- **`agent_tasks.task_session_id`** stops being NULL for delegated
  tasks when the flag is on. Already nullable, additive.

## Migration Path

Three stages, all behind `worker_session_isolation.enabled` (default
false):

1. **Stage 1 — schema + config + manager threading (server, flag off).**
   - `ALTER TABLE agent_messages ADD COLUMN session_id TEXT` (additive).
   - `WorkerSessionIsolationConfig` + TOML wiring.
   - `AGENT_SESSION_FORKED` / `AGENT_SESSION_MERGED` `EventType`s.
   - `AgentManager.send_message` / `store_agent_response` /
     `list_messages` accept an optional `session_id`; `list_messages`
     gains `include_all_sessions: bool = False` so the audit view can
     keep its full read.
   - Loader semantics: when the flag is off, `list_messages` is
     byte-identical to today. When the flag is on AND no `session_id`
     / `include_all_sessions` is passed, untagged-only.
   - Tests: schema present; flag-off reader unchanged; flag-on
     untagged-only behavior; flag-on `include_all_sessions=True`
     returns everything; writes persist `session_id` when passed.

2. **Stage 2 — runtime + tool wiring (flag-gated behavioral change).**
   - `ManagedAgentRuntime.run(...)` reads the task's `task_session_id`
     (when the runner is invoked for a delegated turn) and threads it
     through writes and history loads.
   - `managed_agent_assign_task` mints `session_id` on task creation
     when the flag is on; writes it to `agent_tasks.task_session_id`;
     emits `AGENT_SESSION_FORKED`. The 2F executor's `submit(...)`
     gains a `task_session_id` parameter and passes it to
     `runtime.run(...)`.
   - `managed_agent_delegate` mints an ephemeral session for the
     in-flight delegated turn (no task row in this tool's path);
     emits the same fork event with a synthetic task id of `""`.
   - Parent notification (2F) is reused as the merge act; it emits
     `AGENT_SESSION_MERGED` after `manager.send_message(...)` to the
     parent succeeds.
   - Tests: with flag on, a delegated turn sees only messages scoped
     to its session; two concurrent background delegations against
     the same worker do not interleave; the parent log still receives
     the 2F completion notice; merge event fires once per task; the
     audit view (`include_all_sessions=True`) shows every message.

3. **Stage 3 — opt-in docs, flag stays off.**
   - `docs/user-guide/agents.md` — "Worker session isolation" section.
   - `docs/architecture/overview.md` event table updated for
     `AGENT_SESSION_FORKED` / `AGENT_SESSION_MERGED`.
   - `CHANGELOG.md` entry.
   - `docs/AUGMENTED_FEATURES.md` PROTECTED row added.
   - **The flag is NOT flipped on by default.** Worker session
     isolation changes what context flows into a delegated turn; it
     is an opt-in posture an admin chooses per deployment.

## Rollback Path

- **Stage 3:** revert docs. No code impact.
- **Stage 2:** revert the runtime/tool wiring. The Stage 1 schema +
  flag-gated reader is dormant; no rows are written with a session id.
- **Stage 1:** set `worker_session_isolation.enabled = false` (or
  revert the stage). The `agent_messages.session_id` column is
  nullable and unread when the flag is off — safe to leave or drop.

No destructive data operations at any stage.

## Exact Files Affected

Server (stage 1):
- `src/openjarvis/core/config.py` —
  `WorkerSessionIsolationConfig`; `top_sections`.
- `src/openjarvis/core/events.py` — new `EventType` members.
- `src/openjarvis/agents/manager.py` — migration; `session_id` on
  `send_message` / `store_agent_response`; `session_id` and
  `include_all_sessions` on `list_messages`.
- `tests/agents/test_phase2g_session_threading.py` — new.

Server (stage 2):
- `src/openjarvis/server/managed_agent_runtime.py` — session-aware
  history load + writes when the flag is on and the task carries a
  session id.
- `src/openjarvis/server/background_delegation.py` —
  `BackgroundDelegationExecutor.submit(...)` accepts and threads
  `task_session_id`.
- `src/openjarvis/tools/managed_agent_tools.py` — mint + persist the
  session id in `assign_task` and `delegate`; emit
  `AGENT_SESSION_FORKED`.
- `tests/server/test_phase2g_worker_session_isolation.py` — new.

Frontend (stage 2, audit view):
- `frontend/src/lib/api.ts` — the messages-list call gains an
  `include_all_sessions=true` parameter so the per-agent audit view
  keeps its full read.
- `frontend/src/pages/AgentsPage.tsx` — audit view passes the new
  flag.

Documentation (stage 3):
- `docs/user-guide/agents.md`
- `docs/architecture/overview.md`
- `CHANGELOG.md`
- `docs/AUGMENTED_FEATURES.md`

## Reversibility

**Fully reversible.** The schema column is nullable and unread when the
flag is off. The runtime/tool wiring is a wrapper that is a transparent
pass-through when `worker_session_isolation.enabled` is false. No
endpoint is removed, no schema renamed, no row deleted. Disabling the
flag restores byte-identical pre-change behavior. The audit view's
`include_all_sessions` parameter defaults to `True` for the UI so the
flag-off behavior is preserved without any UI change.

## Approval Question

Do you approve implementing this change as three stages, with:

- the schema, runtime threading, and tool wiring behind
  `worker_session_isolation.enabled` (**default off**, and **kept
  off** — opt-in, not a default behavior change);
- **Option A** (untagged-only reader when the flag is on) as the
  history-loader semantic, with an explicit `include_all_sessions`
  audit hatch;
- reuse of the **Phase 2F parent notification** as the merge act
  (emit `AGENT_SESSION_MERGED` on that write) — no separate
  rollup-summary LLM call in this CIN; and
- **no parent-to-child seeding** in this CIN (Option C deferred)?

If yes, I will build stage 1, stop and report, then stage 2, stop and
report, then stage 3. If you prefer **Option B** (merged view —
`list_messages` returns everything by default even with the flag on,
so isolation is one-way), or want **Option C** (seed the child from
the parent's recent context, via the credential scrubber) in scope,
say so before I start.
