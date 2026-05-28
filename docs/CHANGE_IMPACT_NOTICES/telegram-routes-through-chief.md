# Telegram (and other channels) route through the Chief Orchestrator

## What is changing

When an incoming channel message (Telegram, SMS, etc.) has no explicit
per-channel agent binding, the `ChannelBridge._handle_chat` path now
resolves the same default managed chat agent as `/v1/chat/completions`
(My Assistant → top-level Chief Orchestrator → any Chief Orchestrator)
and runs the message through `ManagedAgentRuntime`, instead of falling
straight through to `JarvisSystem.ask()`.

## Why

The JARVIS Foundation Guide requires the Chief Orchestrator to be the
only human-facing ingress for chat and agent-interact surfaces. The
chat page already enforces this; channel messages did not, so Telegram
users got the bare engine path (no project tools, no news, no
delegation) and saw "I don't have real-time access" responses.

## Benefits

- Channel users get the same tool access as the chat page (news,
  project tools, web search, delegation, etc.).
- Chief-mode delegation is honored on channel messages.
- One ingress code path to reason about for auditing and observability.

## Risks

- If the managed agent runtime is slower than the direct engine path,
  channel reply latency increases by one turn's worth of tool-calling.
- If the default chief agent is misconfigured, channel messages will
  surface that misconfiguration where they previously did not. The
  fallback to `system.ask()` on exception preserves availability.

## Affected files

- `src/openjarvis/server/channel_bridge.py` — `_handle_chat` and new
  `_resolve_default_chat_agent_id` helper.

## User-visible behavior changes

- Telegram messages without an explicit `/agent` binding now answer
  with the same agent, tools, and personality as the chat page.

## Migration

None. No schema, no API contract changes.

## Rollback

Revert `channel_bridge.py` — the fallback to `JarvisSystem.ask()` is
preserved on error, so reverting is safe.

## Approval

Requested directly by the user (channel parity with the chat page).
