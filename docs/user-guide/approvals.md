# Approvals

Approval gating makes a managed agent **pause and wait for a human**
before it runs a sensitive tool. It connects two pieces that already
exist in Jarvis:

- the per-agent `requires_approval_tools` capability axis (which tools
  need sign-off), and
- the approval store (`agent_approvals` table, `/v1/approvals` API,
  `approval.requested` / `approval.resolved` events).

Until you opt in, neither is consulted at tool-dispatch time — the
feature ships **off by default**.

## When to use it

`AGENTS.md` requires that any action which can modify files, run
shell/system commands, access remote services, change agent hierarchy,
alter capability policy, delete data, or disable protections be governed
by approvals or policy. Approval gating is the enforcement mechanism for
that rule. Typical candidates: `delete_files`, `shell_exec`,
`apply_patch`, or any tool that mutates state outside the agent.

## Enabling it

Approval gating is an **opt-in security posture**, chosen per
deployment. It is not turned on automatically, because turning it on
changes whether a tool runs.

Add an `[approval_gating]` section to your `config.toml`:

```toml
[approval_gating]
enabled = true              # default: false
require_human_grant = true  # default: true
timeout_seconds = 0         # default: 0 (no timeout)
```

| Field | Default | Meaning |
|---|---|---|
| `enabled` | `false` | Master switch. While `false`, tool dispatch is byte-identical to a build without this feature. |
| `require_human_grant` | `true` | Rejects a grant whose `resolved_by` is the requesting agent itself — an agent cannot approve its own request. |
| `timeout_seconds` | `0` | Reserved for auto-denying stale requests. `0` means no timeout. |

Then list the gated tools on each agent. The
`requires_approval_tools` capability axis is part of the agent config:

```json
{ "requires_approval_tools": ["delete_files", "shell_exec"] }
```

Only the tools you list are gated; every other tool the agent has runs
freely.

## How a gated call behaves

When an agent calls a tool in its `requires_approval_tools` axis and
gating is enabled, the dispatch gate consults the approval store for the
exact `(agent, capability, arguments)` triple:

- **No prior decision** — the gate creates a `pending` approval request,
  sets the owning task to `awaiting_approval`, and returns a blocking
  result. The agent's turn finishes normally and reports that it is
  paused; it does **not** hang waiting.
- **Granted** — the gate consumes the grant and the tool runs. A grant
  is **single-use**: it authorizes exactly one execution. The next
  identical call needs a fresh grant.
- **Denied** — the tool does not run; the agent receives the denial
  reason as a failed tool result and can adapt.

Grants are **argument-scoped**: approving `delete_files(/tmp/x)` does
not authorize `delete_files(/etc)`. The scope is a SHA-256 over the
normalized arguments (sorted keys, trimmed whitespace), so a trivially
reformatted-but-equivalent call still matches.

## Resolving a request

### From the UI

Pending approvals appear in two places on the Agents page:

- the **Inter-Agent Activity** sidebar (all agents), and
- a card on the **agent Overview** tab (that agent only).

Each entry shows the agent, the capability, and the exact arguments.
**Grant** and **Deny** resolve it.

### From the API

```
GET  /v1/approvals?state=pending
POST /v1/approvals/{id}/grant   { "resolved_by": "...", "reason": "..." }
POST /v1/approvals/{id}/deny    { "resolved_by": "...", "reason": "..." }
```

When the server has no approval store configured, these endpoints
return `503` and the UI simply shows nothing.

## Auto-resume after a grant

Granting a request **re-dispatches the blocked agent** with its original
message (Option B). The agent re-plans with the approval now available,
and the gate consumes the grant when the same call recurs — the human
does not have to re-send anything.

Because the agent re-plans, it *may* not re-issue a byte-identical
call. That is acceptable and arguably more correct; a materially
different action legitimately needs its own approval. Auto-resume only
fires when `approval_gating.enabled` is `true`.

## Scope and limitations

- The gate covers the **managed-agent runtime** only. Direct tool use
  via the CLI (`jarvis ask`) or the Python SDK is **not** gated.
- Decisions are **immutable** once made — a granted or denied request
  cannot be changed; a new request is created for a new call.
- `agent_approvals` rows are append-only; there is no cleanup TTL.

## Rolling back

Set `approval_gating.enabled = false` (or remove the
`[approval_gating]` section). Tool dispatch returns to its
pre-feature behavior immediately. The `agent_approvals` table's
`args_hash` and `consumed_at` columns are nullable and unread while the
flag is off — safe to leave in place.
