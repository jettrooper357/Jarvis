"""ChannelBridge — unified orchestrator for multi-channel messaging."""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

from openjarvis.channels._stubs import BaseChannel, ChannelStatus
from openjarvis.core.events import EventBus, EventType
from openjarvis.server.session_store import SessionStore

logger = logging.getLogger(__name__)

_DEFAULT_MAX_LENGTH = 4000
_SMS_MAX_LENGTH = 1600

_HELP_TEXT = """\
Available commands:
/agents — list running agents
/agent <id> status — agent state and current task
/agent <id> <message> — send a message to an agent
/agent <id> pause — pause an agent
/agent <id> resume — resume an agent
/notify <channel> — set where to receive notifications
/sessions — list your active sessions
/more — get the rest of a truncated response
/help — show this message\
"""

# Events the bridge subscribes to for notifications
_NOTIFICATION_EVENTS = [
    EventType.AGENT_TICK_END,
    EventType.AGENT_TICK_ERROR,
    EventType.AGENT_BUDGET_EXCEEDED,
    EventType.SCHEDULER_TASK_END,
]


class ChannelBridge:
    """Orchestrates incoming messages across multiple channel adapters.

    Provides backward-compatible ``send()``/``status()``/``list_channels()``
    so it can replace the old single-channel bridge in ``app.state``.
    """

    def __init__(
        self,
        channels: Dict[str, BaseChannel],
        session_store: SessionStore,
        bus: EventBus,
        system: Any = None,
        agent_manager: Any = None,
        deep_research_agent: Any = None,
        engine: Any = None,
        default_model: str = "",
    ) -> None:
        self._channels: Dict[str, BaseChannel] = {}
        self._session_store = session_store
        self._bus = bus
        self._system = system
        self._agent_manager = agent_manager
        self._deep_research_agent = deep_research_agent
        self._notification_timestamps: Dict[str, float] = {}
        # Per-agent runtime: when a channel message matches a binding, the
        # bound agent's own config handles it, including managed-agent
        # tool calling and delegation when available.
        self._agent_runtime: Any = None
        if agent_manager is not None and engine is not None:
            try:
                from openjarvis.server.managed_agent_runtime import ManagedAgentRuntime

                self._agent_runtime = ManagedAgentRuntime(
                    agent_manager,
                    engine,
                    bus=bus,
                    default_model=default_model,
                )
            except Exception:
                logger.exception("Failed to build ManagedAgentRuntime")
        self._subscribe_notifications()
        for channel_name, channel in channels.items():
            self.add_channel(channel_name, channel)

    # --------------------------------------------------------------
    # Backward-compatible BaseChannel interface
    # --------------------------------------------------------------

    def connect(self) -> None:
        for ch in self._channels.values():
            ch.connect()

    def disconnect(self) -> None:
        for ch in self._channels.values():
            ch.disconnect()

    def add_channel(self, channel_name: str, channel: BaseChannel) -> None:
        """Register a live channel adapter and wire its incoming handler."""
        self._channels[channel_name] = channel
        try:
            channel.on_message(self._handle_channel_message)
        except Exception:
            logger.exception(
                "Failed to register incoming handler for channel %s",
                channel_name,
            )

    def list_channels(self) -> List[str]:
        result: List[str] = []
        for ch in self._channels.values():
            result.extend(ch.list_channels())
        return result

    def status(self) -> ChannelStatus:
        statuses = [ch.status() for ch in self._channels.values()]
        if not statuses:
            return ChannelStatus.DISCONNECTED
        if any(s == ChannelStatus.CONNECTED for s in statuses):
            return ChannelStatus.CONNECTED
        if all(s == ChannelStatus.ERROR for s in statuses):
            return ChannelStatus.ERROR
        return ChannelStatus.DISCONNECTED

    def send(
        self,
        channel: str,
        content: str,
        *,
        conversation_id: str = "",
        metadata: Dict[str, Any] | None = None,
    ) -> bool:
        for ch in self._channels.values():
            if channel in ch.list_channels():
                return ch.send(
                    channel,
                    content,
                    conversation_id=conversation_id,
                    metadata=metadata,
                )
        logger.warning("No adapter found for channel %s", channel)
        return False

    def _handle_channel_message(self, message) -> None:  # noqa: ANN001
        """Process an incoming channel message and send the reply."""
        sender_id = message.conversation_id or message.sender
        max_length = _SMS_MAX_LENGTH if message.channel in {"twilio", "sendblue"} else _DEFAULT_MAX_LENGTH
        try:
            response = self.handle_incoming(
                sender_id=sender_id,
                content=message.content,
                channel_type=message.channel,
                metadata=getattr(message, "metadata", None),
                max_length=max_length,
            )
        except Exception:
            logger.exception(
                "Incoming channel handler failed for %s",
                message.channel,
            )
            response = "Sorry, I couldn't process that right now. Try again in a moment."

        if not response:
            return

        try:
            self.send(
                message.channel,
                response,
                conversation_id=message.conversation_id or sender_id,
            )
        except Exception:
            logger.exception("Failed to send channel reply on %s", message.channel)

    # --------------------------------------------------------------
    # Incoming message handling
    # --------------------------------------------------------------

    def handle_incoming(
        self,
        sender_id: str,
        content: str,
        channel_type: str,
        metadata: Optional[Dict[str, Any]] = None,
        max_length: int = _DEFAULT_MAX_LENGTH,
    ) -> str:
        self._session_store.get_or_create(sender_id, channel_type)

        # Command routing
        stripped = content.strip()
        if stripped.startswith("/"):
            result = self._handle_command(sender_id, stripped, channel_type)
            if result is not None:
                return result

        # Regular chat — route to JarvisSystem.ask()
        return self._handle_chat(sender_id, stripped, channel_type, max_length)

    # --------------------------------------------------------------
    # Command parsing
    # --------------------------------------------------------------

    def _handle_command(
        self,
        sender_id: str,
        content: str,
        channel_type: str,
    ) -> Optional[str]:
        parts = content.split(None, 2)
        cmd = parts[0].lower()

        if cmd == "/help":
            return _HELP_TEXT

        if cmd == "/more":
            return self._handle_more(sender_id, channel_type)

        if cmd == "/notify" and len(parts) >= 2:
            pref = parts[1]
            self._session_store.set_notification_preference(
                sender_id, channel_type, pref
            )
            return f"Notifications will be sent to {pref}."

        if cmd == "/sessions":
            return self._handle_sessions(sender_id)

        if cmd == "/agents":
            return self._handle_agents_list()

        if cmd == "/agent" and len(parts) >= 2:
            agent_id = parts[1]
            rest = parts[2] if len(parts) > 2 else "status"
            return self._handle_agent_command(agent_id, rest)

        # Unknown command — fall through to chat
        return None

    def _handle_more(self, sender_id: str, channel_type: str) -> str:
        session = self._session_store.get_or_create(sender_id, channel_type)
        pending = session.get("pending_response")
        if pending:
            self._session_store.clear_pending_response(sender_id, channel_type)
            return pending
        return "No pending response."

    def _handle_agents_list(self) -> str:
        if not self._agent_manager:
            return "No agent manager configured."
        agents = self._agent_manager.list_agents()
        if not agents:
            return "No agents currently running."
        lines = []
        for a in agents:
            name = a.get("name", a.get("agent_id", "unknown"))
            status = a.get("status", "unknown")
            lines.append(f"  {name} — {status}")
        return "Running agents:\n" + "\n".join(lines)

    def _handle_agent_command(self, agent_id: str, action: str) -> str:
        if not self._agent_manager:
            return "No agent manager configured."
        action_lower = action.strip().lower()
        state = self._agent_manager.get_agent(agent_id)
        if state is None:
            return f"Agent '{agent_id}' not found."
        if action_lower == "status":
            name = state.get("name", agent_id)
            status = state.get("status", "unknown")
            return f"Agent '{name}': {status}"
        if action_lower == "pause":
            self._agent_manager.pause_agent(agent_id)
            return f"Agent '{agent_id}' paused."
        if action_lower == "resume":
            self._agent_manager.resume_agent(agent_id)
            return f"Agent '{agent_id}' resumed."
        # Treat as an immediate message to the agent when a runtime is available.
        if self._agent_runtime is not None:
            try:
                return self._agent_runtime.run(agent_id, action)
            except Exception:
                logger.exception("Immediate /agent dispatch failed for %s", agent_id)
        result = self._agent_manager.send_message(agent_id, action)
        return str(result) if result else f"Message queued for agent '{agent_id}'."

    # --------------------------------------------------------------
    # Chat handling
    # --------------------------------------------------------------

    def _handle_sessions(self, sender_id: str) -> str:
        targets = self._session_store.get_notification_targets()
        user_sessions = [t for t in targets if t["sender_id"] == sender_id]
        if not user_sessions:
            return "No active sessions with notification preferences."
        lines = []
        for s in user_sessions:
            lines.append(
                f"  {s['channel_type']} -> "
                f"notifications: {s['preferred_notification_channel']}"
            )
        return "Your sessions:\n" + "\n".join(lines)

    def _handle_chat(
        self,
        sender_id: str,
        content: str,
        channel_type: str,
        max_length: int,
    ) -> str:
        self._session_store.append_message(sender_id, channel_type, "user", content)

        # Build context from conversation history
        session = self._session_store.get_or_create(sender_id, channel_type)
        history = session.get("conversation_history", [])
        context_lines = []
        for msg in history[:-1]:  # exclude the message we just appended
            context_lines.append(f"{msg['role']}: {msg['content']}")
        context_str = "\n".join(context_lines)

        query = content
        if context_str:
            query = (
                f"Previous conversation:\n{context_str}\n\nCurrent message: {content}"
            )

        def _preferred_binding(bindings: list[dict]) -> Optional[dict]:
            """Pick the default shared-chat binding when more than one matches.

            Current policy:
            1. Explicit ``routing_mode == "primary"``
            2. Agent whose org role is CEO / Chief Executive Officer
            3. Top-level agent named ``My Assistant`` (case-insensitive)
            4. Sole top-level agent (no manager)
            5. Agent named ``My Assistant`` (case-insensitive)
            6. No implicit preference
            """
            resolved: list[tuple[dict, dict]] = []
            for binding in bindings:
                agent_id = str(binding.get("agent_id", "")).strip()
                if not agent_id or self._agent_manager is None:
                    continue
                try:
                    agent = self._agent_manager.get_agent(agent_id)
                except Exception:
                    logger.exception("get_agent failed for %s", agent_id)
                    continue
                if agent:
                    resolved.append((binding, agent))

            for binding in bindings:
                if str(binding.get("routing_mode", "")).strip().lower() == "primary":
                    return binding

            def _is_ceo(agent: dict) -> bool:
                role = str(agent.get("org_role", "")).strip().casefold()
                return role in {
                    "ceo",
                    "chief executive officer",
                    "chief executive officer (ceo)",
                }

            ceo_bindings = [binding for binding, agent in resolved if _is_ceo(agent)]
            if len(ceo_bindings) == 1:
                return ceo_bindings[0]

            top_level = [
                (binding, agent)
                for binding, agent in resolved
                if not str(agent.get("manager_agent_id", "")).strip()
            ]

            for binding, agent in top_level:
                if str(agent.get("name", "")).strip().casefold() == "my assistant":
                    return binding

            if len(top_level) == 1:
                return top_level[0][0]

            for binding, agent in resolved:
                if str(agent.get("name", "")).strip().casefold() == "my assistant":
                    return binding
            return None

        # Per-agent binding: if this channel/chat_id has a bound agent,
        # route the message to that agent's runtime instead of the global
        # default. Unmatched chats fall through to the existing path.
        if self._agent_runtime is not None and self._agent_manager is not None:
            try:
                bindings = self._agent_manager.find_bindings_for_channel(
                    channel_type, sender_id
                )
            except Exception:
                logger.exception("find_bindings_for_channel failed")
                bindings = []
            if len(bindings) > 1:
                preferred = _preferred_binding(bindings)
                if preferred is None:
                    agent_ids = ", ".join(
                        sorted(
                            str(binding.get("agent_id", ""))
                            for binding in bindings
                            if binding.get("agent_id")
                        )
                    )
                    return (
                        "Multiple agents are bound to this chat. "
                        f"Use /agent <id> <message>. Bound agents: {agent_ids}"
                    )
                binding = preferred
            else:
                binding = bindings[0] if bindings else None
            if binding:
                agent_id = binding.get("agent_id")
                if agent_id:
                    try:
                        response_text = self._agent_runtime.run(agent_id, content)
                        formatted = self._format_response(
                            sender_id, channel_type, response_text, max_length
                        )
                        self._session_store.append_message(
                            sender_id, channel_type, "assistant", response_text
                        )
                        return formatted
                    except Exception:
                        logger.exception(
                            "Bound agent %s failed; falling back to default",
                            agent_id,
                        )

        # Try DeepResearchAgent first
        if self._deep_research_agent is not None:
            try:
                result = self._deep_research_agent.run(content)
                response_text = result.content or "No results found."
            except Exception as exc:
                logger.error("DeepResearch agent failed: %s", exc)
                response_text = f"Research error: {exc}"
        elif self._system is not None:
            try:
                result = self._system.ask(query)
                response_text = result.get("content", str(result))
            except Exception:
                logger.exception("Error in JarvisSystem.ask()")
                error_msg = (
                    "Sorry, I couldn't process that right now. Try again in a moment."
                )
                self._session_store.append_message(
                    sender_id, channel_type, "assistant", error_msg
                )
                return error_msg
        else:
            error_msg = (
                "Sorry, I couldn't process that right now. Try again in a moment."
            )
            self._session_store.append_message(
                sender_id, channel_type, "assistant", error_msg
            )
            return error_msg

        # Format and possibly truncate
        formatted = self._format_response(
            sender_id, channel_type, response_text, max_length
        )
        self._session_store.append_message(
            sender_id, channel_type, "assistant", response_text
        )
        return formatted

    def _format_response(
        self,
        sender_id: str,
        channel_type: str,
        response: str,
        max_length: int,
    ) -> str:
        if len(response) <= max_length:
            return response
        # Truncate and store full response for /more retrieval
        truncation_notice = "\n\n... (reply /more for full response)"
        cut_at = max_length - len(truncation_notice)
        truncated = response[:cut_at] + truncation_notice
        self._session_store.set_pending_response(sender_id, channel_type, response)
        return truncated

    # --------------------------------------------------------------
    # Notifications
    # --------------------------------------------------------------

    def _subscribe_notifications(self) -> None:
        for event_type in _NOTIFICATION_EVENTS:
            self._bus.subscribe(event_type, self._on_notification_event)

    def _on_notification_event(self, event) -> None:  # noqa: ANN001
        event_key = str(event.event_type)
        now = time.time()

        # Rate limit: max 1 per event type per 5 minutes
        last = self._notification_timestamps.get(event_key, 0)
        if now - last < 300:
            return
        self._notification_timestamps[event_key] = now

        message = self._format_notification(event)
        if not message:
            return

        targets = self._session_store.get_notification_targets()
        for target in targets:
            pref_channel = target["preferred_notification_channel"]
            sender_id = target["sender_id"]
            self._send_notification(pref_channel, sender_id, message)

    def _format_notification(  # noqa: ANN201
        self,
        event,  # noqa: ANN001
    ) -> Optional[str]:
        data = event.data or {}
        name = data.get("agent_name", data.get("name", "unknown"))

        if event.event_type == EventType.AGENT_TICK_END:
            summary = data.get("summary", data.get("result", ""))
            return f"Agent '{name}' finished: {summary}" if summary else None
        if event.event_type == EventType.AGENT_TICK_ERROR:
            error = data.get("error", "unknown error")
            return f"Agent '{name}' error: {error}"
        if event.event_type == EventType.AGENT_BUDGET_EXCEEDED:
            return f"Agent '{name}' hit budget limit."
        if event.event_type == EventType.SCHEDULER_TASK_END:
            if data.get("success", True):
                return f"Scheduled task '{name}' completed."
            error = data.get("error", "unknown error")
            return f"Scheduled task '{name}' failed: {error}"
        return None

    def _send_notification(
        self,
        channel_type: str,
        sender_id: str,
        message: str,
    ) -> None:
        ch = self._channels.get(channel_type)
        if ch is None:
            logger.warning(
                "No adapter for notification channel %s",
                channel_type,
            )
            return
        try:
            ch.send(sender_id, message)
        except Exception:
            logger.exception("Failed to send notification to %s", channel_type)
