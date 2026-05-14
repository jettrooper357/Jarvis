"""Per-agent runtime cache used by channel dispatch.

When a channel message (e.g. a Telegram DM) arrives and matches a
``channel_bindings`` row, :class:`AgentRuntimeCache` is the bridge that
runs the message against *that specific agent's* config (model,
system_prompt, temperature) instead of the server's global default
agent. Runtimes are lazily built on first use and cached in memory; the
cache is invalidated when a binding is removed.

The cache intentionally stays light — it doesn't reconstruct the full
managed-agent streaming/tool-use loop that lives in
``server.agent_manager_routes``. It calls ``engine.generate`` once per
turn with the agent's system_prompt + recent history, persists the
turn in ``agent_messages``, and returns the response text. Tool calling
and deep_research wiring can be layered on later without changing the
public surface.
"""

from __future__ import annotations

import logging
import threading
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class AgentRuntimeCache:
    """Lazy, in-memory cache of per-agent runtime configs."""

    def __init__(
        self,
        manager: Any,
        engine: Any,
        *,
        default_model: str = "",
        history_limit: int = 10,
    ) -> None:
        self._manager = manager
        self._engine = engine
        self._default_model = default_model
        self._history_limit = history_limit
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()

    def invalidate(self, agent_id: str) -> None:
        """Drop a cached runtime so the next call rebuilds from DB."""
        with self._lock:
            self._cache.pop(agent_id, None)

    def _get_or_build(self, agent_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            cached = self._cache.get(agent_id)
        if cached is not None:
            return cached

        record = self._manager.get_agent(agent_id)
        if record is None:
            return None
        config = record.get("config", {}) or {}
        runtime: Dict[str, Any] = {
            "agent_id": agent_id,
            "agent_type": record.get("agent_type", ""),
            "model": config.get("model") or self._default_model,
            "system_prompt": config.get("system_prompt", ""),
            "temperature": float(config.get("temperature", 0.7)),
            "max_tokens": int(config.get("max_tokens", 1024)),
        }
        with self._lock:
            self._cache.setdefault(agent_id, runtime)
            return self._cache[agent_id]

    def run(self, agent_id: str, user_content: str) -> str:
        """Run one turn through the agent and return its response text."""
        runtime = self._get_or_build(agent_id)
        if runtime is None:
            raise KeyError(f"Agent {agent_id!r} not found")
        if self._engine is None:
            raise RuntimeError("No engine configured for agent runtime")

        from openjarvis.core.types import Message, Role

        messages = []
        if runtime["system_prompt"]:
            messages.append(
                Message(role=Role.SYSTEM, content=runtime["system_prompt"])
            )
        # list_messages returns DESC; reverse for chronological order.
        history = self._manager.list_messages(agent_id, limit=self._history_limit)
        for m in reversed(history):
            if m.get("direction") == "user_to_agent":
                messages.append(Message(role=Role.USER, content=m["content"]))
            elif m.get("direction") == "agent_to_user":
                messages.append(Message(role=Role.ASSISTANT, content=m["content"]))
        messages.append(Message(role=Role.USER, content=user_content))

        try:
            self._manager.send_message(agent_id, user_content, mode="channel")
        except Exception:
            logger.exception("Failed to persist user message for %s", agent_id)

        try:
            result = self._engine.generate(
                messages,
                model=runtime["model"],
                temperature=runtime["temperature"],
                max_tokens=runtime["max_tokens"],
            )
            response_text = (
                result.get("content") if isinstance(result, dict) else str(result)
            ) or ""
        except Exception as exc:
            logger.exception("engine.generate failed for agent %s", agent_id)
            return f"Sorry, the agent failed: {exc}"

        try:
            self._manager.add_agent_response(agent_id, response_text)
        except Exception:
            logger.exception("Failed to persist agent response for %s", agent_id)

        return response_text


__all__ = ["AgentRuntimeCache"]
