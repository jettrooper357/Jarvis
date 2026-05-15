"""Synchronous managed-agent runtime used by channel dispatch and delegation."""

from __future__ import annotations

import contextvars
import logging
import time
from contextlib import contextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Dict, Iterator, List, Optional, Sequence

from openjarvis.agents.capabilities import (
    build_agent_tool_instances,
    effective_agent_tool_names as _effective_capability_tool_names,
)
from openjarvis.core.events import EventType
from openjarvis.core.types import Message, Role, ToolCall, ToolResult
from openjarvis.tools._stubs import ToolExecutor

if TYPE_CHECKING:
    from openjarvis.tools._stubs import BaseTool

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ManagedAgentExecutionContext:
    """Runtime state exposed to delegation-aware tools via a context var."""

    runtime: "ManagedAgentRuntime"
    manager: Any
    engine: Any
    current_agent_id: str
    parent_agent_id: str = ""
    visited_agent_ids: tuple[str, ...] = ()


_execution_context: contextvars.ContextVar[ManagedAgentExecutionContext | None] = (
    contextvars.ContextVar("openjarvis_managed_agent_execution", default=None)
)


def get_managed_agent_context() -> ManagedAgentExecutionContext | None:
    """Return the current managed-agent tool execution context, if any."""
    return _execution_context.get()


@contextmanager
def use_managed_agent_context(
    context: ManagedAgentExecutionContext,
) -> Iterator[ManagedAgentExecutionContext]:
    """Bind managed-agent runtime state for tool execution."""
    token = _execution_context.set(context)
    try:
        yield context
    finally:
        _execution_context.reset(token)


def _tool_call_name(raw: Dict[str, Any]) -> str:
    function = raw.get("function")
    if isinstance(function, dict):
        return str(function.get("name", ""))
    return str(raw.get("name", ""))


def _tool_call_args(raw: Dict[str, Any]) -> str:
    function = raw.get("function")
    if isinstance(function, dict):
        return str(function.get("arguments", ""))
    return str(raw.get("arguments", ""))


def _response_content(result: Any) -> str:
    if isinstance(result, dict):
        return str(result.get("content", "") or "")
    return str(result or "")


def _effective_tool_names(agent_record: Dict[str, Any]) -> List[str]:
    return _effective_capability_tool_names(agent_record)


def _should_enable_knowledge(agent_record: Dict[str, Any]) -> bool:
    from openjarvis.agents.capabilities import should_enable_agent_knowledge

    return should_enable_agent_knowledge(agent_record)


class ManagedAgentRuntime:
    """Run managed agents synchronously with tool-calling and delegation."""

    def __init__(
        self,
        manager: Any,
        engine: Any,
        *,
        bus: Any = None,
        default_model: str = "",
    ) -> None:
        self._manager = manager
        self._engine = engine
        self._bus = bus
        self._default_model = default_model

    def run(
        self,
        agent_id: str,
        user_content: str,
        *,
        parent_agent_id: str = "",
        visited_agent_ids: Optional[Sequence[str]] = None,
    ) -> str:
        agent_record = self._manager.get_agent(agent_id)
        if agent_record is None:
            raise KeyError(f"Agent {agent_id!r} not found")

        mode = "delegated" if parent_agent_id else "channel"
        started_at = time.time()
        agent_name = str(agent_record.get("name", agent_id))
        if self._bus is not None:
            try:
                self._bus.publish(
                    EventType.AGENT_TICK_START,
                    {
                        "agent_id": agent_id,
                        "agent_name": agent_name,
                        "mode": mode,
                    },
                )
            except Exception:
                logger.exception("Failed to publish AGENT_TICK_START for %s", agent_id)
        message = self._manager.send_message(agent_id, user_content, mode=mode)
        message_id = message["id"]
        if self._bus is not None:
            try:
                self._bus.publish(
                    EventType.AGENT_MESSAGE_RECEIVED,
                    {
                        "agent_id": agent_id,
                        "agent_name": agent_name,
                        "message_id": message_id,
                        "mode": mode,
                    },
                )
            except Exception:
                logger.exception(
                    "Failed to publish AGENT_MESSAGE_RECEIVED for %s",
                    agent_id,
                )
        response_text = ""
        tool_calls: Optional[List[Dict[str, Any]]] = None
        had_error = False
        try:
            response_text, tool_calls = self._run_turn(
                agent_record=agent_record,
                user_content=user_content,
                message_id=message_id,
                parent_agent_id=parent_agent_id,
                visited_agent_ids=visited_agent_ids or (),
            )
        except Exception as exc:
            logger.exception("Managed agent turn failed for %s", agent_id)
            response_text = f"Sorry, the agent failed: {exc}"
            had_error = True
        finally:
            try:
                self._manager.mark_message_delivered(message_id)
            except Exception:
                logger.exception("Failed to mark message delivered for %s", agent_id)
        self._manager.store_agent_response(
            agent_id,
            response_text,
            tool_calls=tool_calls or None,
        )
        if self._bus is not None:
            try:
                event_type = EventType.AGENT_TICK_ERROR if had_error else EventType.AGENT_TICK_END
                payload = {
                    "agent_id": agent_id,
                    "agent_name": agent_name,
                    "duration": time.time() - started_at,
                    "status": "error" if had_error else "ok",
                    "summary": response_text[:240],
                }
                if had_error:
                    payload["error"] = response_text[:240]
                self._bus.publish(event_type, payload)
            except Exception:
                logger.exception("Failed to publish completion event for %s", agent_id)
        return response_text

    def _run_turn(
        self,
        *,
        agent_record: Dict[str, Any],
        user_content: str,
        message_id: str,
        parent_agent_id: str,
        visited_agent_ids: Sequence[str],
    ) -> tuple[str, List[Dict[str, Any]]]:
        agent_id = agent_record["id"]
        config = agent_record.get("config", {}) or {}
        model = config.get("model") or getattr(self._engine, "_model", "") or self._default_model
        if not model:
            raise RuntimeError("No model configured for managed agent runtime")

        execution_context = ManagedAgentExecutionContext(
            runtime=self,
            manager=self._manager,
            engine=self._engine,
            current_agent_id=agent_id,
            parent_agent_id=parent_agent_id,
            visited_agent_ids=tuple(visited_agent_ids),
        )

        with use_managed_agent_context(execution_context):
            if agent_record.get("agent_type", "") == "deep_research":
                return self._run_deep_research_turn(
                    agent_record=agent_record,
                    user_content=user_content,
                    model=model,
                    execution_context=execution_context,
                )
            return self._run_standard_turn(
                agent_record=agent_record,
                user_content=user_content,
                message_id=message_id,
                model=model,
                execution_context=execution_context,
            )

    def _run_deep_research_turn(
        self,
        *,
        agent_record: Dict[str, Any],
        user_content: str,
        model: str,
        execution_context: ManagedAgentExecutionContext,
    ) -> tuple[str, List[Dict[str, Any]]]:
        from openjarvis.agents.deep_research import DeepResearchAgent

        config = agent_record.get("config", {}) or {}
        tools = build_agent_tool_instances(
            agent_record,
            engine=self._engine,
            model=model,
            bus=self._bus,
            execution_context=execution_context,
            interactive=True,
            confirm_callback=lambda _prompt: True,
        )
        collected_tool_calls: List[Dict[str, Any]] = []

        dr_agent = DeepResearchAgent(
            engine=self._engine,
            model=model,
            tools=tools,
            bus=self._bus,
            max_turns=int(config.get("max_turns", 8)),
            temperature=float(config.get("temperature", 0.3)),
            max_tokens=int(config.get("max_tokens", 4096)),
            interactive=True,
            confirm_callback=lambda _prompt: True,
        )

        original_execute = dr_agent._executor.execute

        def _tracked_execute(tool_call: ToolCall) -> ToolResult:
            result = original_execute(tool_call)
            collected_tool_calls.append(
                {
                    "tool": tool_call.name,
                    "arguments": tool_call.arguments or "",
                    "result": result.content or "",
                    "success": bool(result.success),
                    "latency": float(result.latency_seconds or 0.0),
                }
            )
            return result

        dr_agent._executor.execute = _tracked_execute
        result = dr_agent.run(user_content)
        return result.content or "No results found.", collected_tool_calls

    def _run_standard_turn(
        self,
        *,
        agent_record: Dict[str, Any],
        user_content: str,
        message_id: str,
        model: str,
        execution_context: ManagedAgentExecutionContext,
    ) -> tuple[str, List[Dict[str, Any]]]:
        config = agent_record.get("config", {}) or {}
        tool_instances = build_agent_tool_instances(
            agent_record,
            engine=self._engine,
            model=model,
            bus=self._bus,
            execution_context=execution_context,
            interactive=True,
            confirm_callback=lambda _prompt: True,
        )
        tool_specs = [tool.to_openai_function() for tool in tool_instances]
        tool_map = {tool.spec.name: tool for tool in tool_instances}

        messages: List[Message] = []
        system_prompt = config.get("system_prompt")
        if system_prompt:
            messages.append(Message(role=Role.SYSTEM, content=str(system_prompt)))

        history = self._manager.list_messages(agent_record["id"], limit=50)
        for item in reversed(history):
            if item["id"] == message_id:
                continue
            if item["direction"] == "user_to_agent":
                messages.append(Message(role=Role.USER, content=item["content"]))
            elif item["direction"] == "agent_to_user":
                messages.append(Message(role=Role.ASSISTANT, content=item["content"]))
        messages.append(Message(role=Role.USER, content=user_content))

        temperature = float(config.get("temperature", 0.7))
        max_tokens = int(config.get("max_tokens", 1024))
        max_turns = int(config.get("max_turns", 10))
        collected_prefix = ""
        collected_tool_calls: List[Dict[str, Any]] = []

        for _turn in range(max_turns):
            kwargs: Dict[str, Any] = {
                "model": model,
                "temperature": temperature,
                "max_tokens": max_tokens,
            }
            if tool_specs:
                kwargs["tools"] = tool_specs
            result = self._engine.generate(messages, **kwargs)
            turn_content = _response_content(result)
            tool_calls_raw = result.get("tool_calls", []) if isinstance(result, dict) else []

            if not tool_calls_raw:
                return f"{collected_prefix}{turn_content}", collected_tool_calls

            messages.append(
                Message(
                    role=Role.ASSISTANT,
                    content=turn_content,
                    tool_calls=[
                        ToolCall(
                            id=str(raw.get("id", "")),
                            name=_tool_call_name(raw),
                            arguments=_tool_call_args(raw),
                        )
                        for raw in tool_calls_raw
                    ],
                )
            )

            for raw in tool_calls_raw:
                tool_name = _tool_call_name(raw)
                tool_args = _tool_call_args(raw)
                tool_result_content = f"Tool '{tool_name}' not available"
                tool_success = False
                try:
                    tool = tool_map.get(tool_name)
                    if tool is None:
                        raise KeyError(tool_name)
                    executor = ToolExecutor(
                        tools=[tool],
                        bus=self._bus,
                        interactive=True,
                        confirm_callback=lambda _prompt: True,
                    )
                    result_obj = executor.execute(
                        ToolCall(
                            id=str(raw.get("id", "")),
                            name=tool_name,
                            arguments=tool_args,
                        )
                    )
                    tool_result_content = result_obj.content or ""
                    tool_success = bool(result_obj.success)
                except Exception as exc:
                    logger.exception("Managed agent tool execution failed for %s", tool_name)
                    tool_result_content = f"Error executing {tool_name}: {exc}"

                collected_tool_calls.append(
                    {
                        "tool": tool_name,
                        "arguments": tool_args,
                        "result": tool_result_content,
                        "success": tool_success,
                        "latency": 0.0,
                    }
                )
                messages.append(
                    Message(
                        role=Role.TOOL,
                        content=tool_result_content,
                        tool_call_id=str(raw.get("id", "")),
                        name=tool_name,
                    )
                )

            collected_prefix += turn_content

        messages.append(
            Message(
                role=Role.USER,
                content=(
                    "Write the best final answer you can from the completed tool results. "
                    "Do not call more tools."
                ),
            )
        )
        fallback = self._engine.generate(
            messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return f"{collected_prefix}{_response_content(fallback)}", collected_tool_calls
