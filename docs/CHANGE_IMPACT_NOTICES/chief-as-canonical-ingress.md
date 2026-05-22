# Change Impact Notice: Chief as Canonical Ingress

> **Phase 2E** of `docs/PHASE_2_PLAN.md`. Generated 2026-05-20.
> **Status:** awaiting explicit approval. **No code written.**

## What Would Change

Make the **Chief Orchestrator** the canonical ingress for user-facing
chat and agent-interact traffic, without removing the
OpenAI-compatible `/v1/chat/completions` surface and without removing
direct-to-subordinate messaging.

Concretely, three additive layers and two default-behavior switches:

1. **Identification — additive schema (`managed_agents`).**
   - Add a nullable boolean column `is_chief INTEGER DEFAULT 0`.
   - Add a helper `AgentManager.get_chief_agent()` that returns the row
     where `is_chief = 1` (uniqueness enforced at write time).
   - Add `AgentManager.set_chief_agent(agent_id)` that atomically
     clears the flag from any prior row and sets it on the named row.
   - Back-fill rule on startup: if no row has `is_chief = 1`, mark the
     first agent whose `org_role` (case-insensitive) matches one of
     `"chief orchestrator"`, `"chief executive officer"`, `"ceo"` —
     today's *de facto* Chief identity (already used by
     `managed_agent_runtime.py:102-105` for the chief role guidance).
     If still none, leave it unset (the new endpoint then returns 412
     so the UI prompts the user to designate one).

2. **New endpoint (additive) — `POST /v1/chief/messages`.**
   - Body: `{content: string, mode?: 'immediate'|'queued', stream?: bool,
     requesting_user?: string}`.
   - Behavior: resolves the Chief agent via `get_chief_agent()`. If
     none configured, returns **412 Precondition Required** with a
     payload telling the UI to designate a Chief. Otherwise dispatches
     the message through the existing managed-agent runtime path that
     already powers `/v1/managed-agents/{id}/messages`. SSE response
     when `stream=true`, JSON otherwise. Same event/telemetry/trace
     shape as the existing endpoint — this is a thin routing wrapper,
     not a new runtime.
   - Records the inbound request as a **root task** in `agent_tasks`
     with `request_source = "chief_chat"` or `"chief_interact"` and
     `requesting_user` populated from the body — using the columns
     already added in Phase 2A.

3. **Configuration flag — `[chief_ingress]` in `config.toml`.**
   - `chief_ingress.enabled` (default `false` on first deploy, then
     flipped to `true` by a follow-up commit once the rollout window
     ends). Front-end gates the toggle on the `health` endpoint
     reporting `chief_ingress.enabled` and a Chief being designated.

4. **Default routing switch — `ChatPage`.**
   - `frontend/src/components/Chat/InputArea.tsx` switches its default
     send path from `streamChat()` (which hits
     `/v1/chat/completions`) to a new `sendChiefMessage()` (which
     hits `/v1/chief/messages`) when `chief_ingress.enabled` is true
     and a Chief is configured.
   - Adds a **"Direct"** toggle (off by default) that falls back to
     the legacy `/v1/chat/completions` path. Power users keep their
     escape hatch.

5. **Default routing switch — Agent-interact tab.**
   - `frontend/src/pages/AgentsPage.tsx::InteractTab` adds a **"Route
     through Chief"** toggle:
     - Default **ON** for any subordinate (non-Chief) agent.
     - Default **OFF** for the Chief itself (so InteractTab on the
       Chief still uses `/v1/managed-agents/{chief_id}/messages`, which
       is functionally identical to the new endpoint).
   - When the toggle is on, the message is sent to `/v1/chief/messages`
     with a hint (`target_agent_id`) telling the Chief who the user
     was trying to reach. The Chief decides whether to delegate to
     that agent, decompose, or answer directly.

What is **not** in this change:
- `/v1/chat/completions` stays bit-identical for third-party
  OpenAI-compatible clients.
- `/v1/managed-agents/{id}/messages` stays available — direct
  messaging an agent is still possible (it's now opt-in for
  subordinates, opt-out for the Chief).
- No change to the orchestrator agent itself or `OrchestratorAction`
  envelope; the Chief is the existing `OrchestratorAgent(mode="chief")`.
- No change to event types — `task.created/updated/delegated/completed/failed`
  already cover this and were added in Phase 2A.
- No change to capability resolution.

## Why It Is Needed

Drift item §4.1 in `docs/ARCHITECTURE_DRIFT_REPORT.md` — the
**highest-severity** invariant violation in `AGENTS.md`:

> "All requests from the chat page and the agent-interact page must
> enter through the Chief Orchestrator."

Today neither page enforces this. `ChatPage` hits the generic
`/v1/chat/completions`; the Agent-interact tab speaks to whichever
agent the user clicked into. Without the Chief in the loop, the
hierarchical chain-of-command is decorative — there's no place that
decides "answer directly vs delegate vs decompose," no root task is
recorded for chat-page traffic, and no upward return path is
guaranteed.

## Benefits

- **Single ingress = single source of operational truth.** Every
  user message becomes a root task in `agent_tasks` with a stable
  `request_source`, surfaceable in Mission Control and the activity
  sidebar.
- **Delegation becomes observable.** Phase 2C already emits
  `task.delegated` events when one agent's `assigned_by_agent_id` is
  another agent — wiring the Chief as ingress means **every**
  user-originated delegation flows through that signal automatically.
- **Upward return path becomes structural, not accidental.** Today a
  subordinate's reply goes straight to the human; tomorrow it returns
  through the Chief, which can summarize, follow up, or present
  errors uniformly.
- **Approval flow has a home.** Phase 2D's `agent_approvals` rows
  attach naturally to the Chief's root task; the Chief can pause
  ("awaiting_approval") and resume the conversation when granted.
- **Doesn't break third-party clients.** `/v1/chat/completions` stays
  untouched — anything reading the OpenAI-compatible surface
  continues to work.

## Risks

| Risk | Severity | Mitigation |
|---|---|---|
| User confusion: "why is my message going to a different agent?" | **High** (UX) | UI shows a Chief avatar/banner above the chat input; "Direct" toggle visible; "Route through Chief" toggle on InteractTab labeled clearly. |
| Added latency: Chief makes one extra LLM hop to decide route | Medium | Chief's existing system prompt already includes "answer directly when possible" guidance (`managed_agent_runtime.py:109-127`). For chat where the Chief answers itself, latency is ~unchanged. For delegated work, the second hop is the real subordinate run, which would have happened anyway. |
| Tests that talk to `/v1/chat/completions` directly behave unchanged | Low | We are not touching `/v1/chat/completions`. Existing 30 route tests still pass after Phase 2A–2D. |
| **No Chief designated** on first run | Medium | The 412 response includes a CTA payload `{action: "designate_chief", agents: [...]}` so the UI prompts the user to pick one. Back-fill rule auto-promotes the first agent matching the today's chief-role heuristic. |
| Multiple agents marked as chief (concurrent admin edits) | Low | `set_chief_agent` is atomic: clears all rows then sets one in a single transaction. UNIQUE-like enforcement via `WHERE is_chief = 1` count check before commit. |
| The Chief becomes a single point of failure for chat | Medium | Direct routes are preserved. If the Chief is paused / errored, the UI degrades to a banner "Chief is unavailable — use Direct mode" and the existing `/v1/chat/completions` toggle still works. |
| Performance regression on InteractTab for power users who *want* direct talk | Low–Medium | "Route through Chief" toggle defaults ON for subordinates but the user can flip it off per-session. Selection is remembered in `useAppStore`. |
| Chief loop: user sends message → Chief delegates to subordinate → subordinate calls `managed_agent_delegate` back to Chief → infinite recursion | Medium | Already mitigated by existing `visited_agent_ids` cycle protection in `ManagedAgentExecutionContext` (managed_agent_runtime.py:29-42). Add a test exercising user→Chief→subordinate→Chief flow to lock that behavior in. |
| Migration on installs with **no** agents yet | Low | Endpoint returns 412 with a CTA; UI guides the user through agent creation as it does today. |

## Side Effects

- **`agent_tasks` row volume increases.** Every chat-page message
  becomes a root task. Existing rows are unaffected. Cleanup TTL is
  not part of this change (defer).
- **`AGENT_MESSAGE_RECEIVED` event volume increases** by exactly one
  per inbound user message — the Chief receives every user message
  by default. Subscribers ignore events they don't care about, so no
  consumer changes are needed.
- **The Chief's `total_runs` / `input_tokens` / `output_tokens`
  metrics climb faster** than today (since every chat goes through
  it). Mission Control and the "Dollars Saved vs." panel still
  display per-agent, but the Chief row will become the highest by a
  wide margin. Acceptable per the new architecture; flag for the
  Capability Inspector's "Local Utilization" cards which may want a
  "vs. cloud" comparison normalized differently for the Chief.
- **Frontend `ManagedAgent` interface gains `is_chief?: boolean`** —
  additive optional field; existing consumers ignore it.
- **`enrich_agent_record` output gains `is_chief: bool`** key —
  same JSON-contract additive treatment as the Phase 2A axes.

## Migration Path

Phased over three commits, all behind the `chief_ingress.enabled`
config flag:

1. **Commit 1 — Schema + back-fill + endpoint (server-only).**
   - ALTER TABLE `managed_agents` ADD COLUMN `is_chief INTEGER
     DEFAULT 0`.
   - Back-fill: SET `is_chief = 1` for the first row matching the
     chief-role heuristic; ignore if none.
   - Add `get_chief_agent()` / `set_chief_agent()` helpers.
   - Add `POST /v1/chief/messages` (returns 412 when no Chief or
     when flag is off).
   - Add `is_chief` to `enrich_agent_record` output.
   - **No frontend change.** `/v1/chat/completions` and
     `/v1/managed-agents/{id}/messages` behave identically.
   - **Tests:** schema migration, back-fill, endpoint returns 412
     when off, endpoint dispatches correctly when on, multi-chief
     guard.

2. **Commit 2 — Frontend wiring (UI gated on health flag).**
   - `sendChiefMessage()` in `lib/api.ts`.
   - `ChatPage` / `InputArea` switches default path when health
     reports `chief_ingress.enabled = true` and a Chief is set.
   - `InteractTab` adds the "Route through Chief" toggle.
   - "Direct" toggle on `ChatPage`.
   - Capability Inspector: visual "Chief" badge on the Chief agent
     in `AgentOrgChart` (already pulses on activity; new badge is
     additive).
   - **Tests:** ChatPage default routing, toggle behavior,
     InteractTab toggle defaults.

3. **Commit 3 — Flip the flag.**
   - Default `chief_ingress.enabled = true` in `configs/openjarvis/*`.
   - Release notes + `CHANGELOG.md` entry.
   - Update `docs/user-guide/agents.md` and `docs/user-guide/cli.md`
     to describe the Chief-as-ingress behavior.
   - Update `docs/architecture/overview.md` query-flow diagram.

Each commit lands separately. If commit 2 surfaces unacceptable UX
issues, commit 3 is held — the system stays on the legacy default
with the new endpoint dormant.

## Rollback Path

- **Commit 3 rollback:** flip flag back to `false`. Frontend snaps to
  the legacy `/v1/chat/completions` and direct `/v1/managed-agents/{id}/messages`
  paths in the next page load.
- **Commit 2 rollback:** revert the frontend commit; backend
  endpoint stays dormant (no effect when no client calls it).
- **Commit 1 rollback:** drop the `is_chief` column and remove the
  endpoint. The column is nullable and unread by anything else, so
  drop is safe.

Per-commit, no destructive data operations.

## Exact Files Affected

Server (commit 1):
- `src/openjarvis/agents/manager.py` — schema migration; `get_chief_agent`, `set_chief_agent`; `_row_to_agent` adds `is_chief` key.
- `src/openjarvis/server/agent_manager_routes.py` — new `POST /v1/chief/messages`; extend `_enrich_agent_record` to surface `is_chief`.
- `src/openjarvis/server/managed_agent_runtime.py` — no logic change; the new endpoint reuses the existing dispatch path.
- `src/openjarvis/core/config.py` — add `chief_ingress.enabled` config field, default `false`.
- `tests/agents/test_phase2e_chief_designation.py` — new.
- `tests/server/test_phase2e_chief_messages_route.py` — new.

Frontend (commit 2):
- `frontend/src/lib/api.ts` — `sendChiefMessage()`; `ManagedAgent.is_chief?`.
- `frontend/src/components/Chat/InputArea.tsx` — default routing switch; Direct toggle.
- `frontend/src/pages/AgentsPage.tsx` — `InteractTab` adds "Route through Chief" toggle; `AgentOrgChart` Chief badge; capability-inspector banner.
- `frontend/src/lib/store.ts` — persist the toggle state.
- `frontend/src/hooks/useChiefHealth.ts` — new tiny hook polling whether ingress is enabled + Chief is designated.

Documentation (commit 3):
- `docs/user-guide/agents.md`
- `docs/user-guide/cli.md`
- `docs/architecture/overview.md` (query-flow section)
- `CHANGELOG.md`
- `docs/AUGMENTED_FEATURES.md` — add the new Chief-ingress route + endpoint under "Chain-of-command primitives".
- `docs/FEATURE_PRESERVATION_MATRIX.md` — mark `POST /v1/chief/messages` as protected once it ships.

## Reversibility

**Fully reversible** at every commit boundary:
- The new `is_chief` column is nullable and unread by anything outside
  the new helpers — `DROP COLUMN` (or the SQLite equivalent of marking
  it ignored) is safe.
- The new endpoint is additive; removal has no consumer cleanup.
- The frontend changes are behind the `chief_ingress.enabled` flag;
  flipping it off restores the legacy default routing.
- `/v1/chat/completions` and `/v1/managed-agents/{id}/messages` are
  never touched.
- No destructive data migration; no row deletion; no schema rename.

## Approval Question

Do you approve implementing this change as three sequential commits,
with the default flag flip (commit 3) held until you explicitly say
"flip it"?

If yes, I will:
1. Build commit 1 (server-only, flag off, fully tested).
2. Stop and report.
3. Build commit 2 (frontend wiring, flag still off — invisible to
   users until you flip it).
4. Stop and report.
5. Hold commit 3 indefinitely until you instruct.

If you'd like a different shape — e.g. commits 1 + 2 in one pass, or a
fourth commit splitting the migration from the back-fill — say so
before I start.
