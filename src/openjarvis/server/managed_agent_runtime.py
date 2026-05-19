"""Synchronous managed-agent runtime used by channel dispatch and delegation."""

from __future__ import annotations

import contextvars
import logging
import time
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Dict, Iterator, List, Optional, Sequence

from openjarvis.agents.capabilities import (
    build_agent_tool_instances,
)
from openjarvis.agents.capabilities import (
    effective_agent_tool_names as _effective_capability_tool_names,
)
from openjarvis.core.events import EventType
from openjarvis.core.types import Message, Role, ToolCall, ToolResult
from openjarvis.tools._stubs import ToolExecutor

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


def _role_guidance(agent_record: Dict[str, Any]) -> str:
    role = str(agent_record.get("org_role", "") or "").strip()
    # No early return for a missing role: every agent gets baseline triage
    # rules via the generic default at the end of this function.
    role_key = role.casefold()
    is_chief = (
        "chief orchestrator" in role_key
        or "chief executive officer" in role_key
        or role_key == "ceo"
    )
    if is_chief:
        return (
            "Use your own capabilities FIRST:\n"
            "- You have connected data sources, skills, and presets. Use "
            "them to answer directly. Query your knowledge with "
            "knowledge_search (it covers your connected data sources — "
            "e.g. News/RSS, Hacker News, email, calendar, drive) and run "
            "any skill/preset configured for you.\n"
            "- NEVER claim you 'do not have access' to news, current "
            "events, or any topic without first calling knowledge_search. "
            "If a relevant data source or skill is configured for you, you "
            "DO have access — use it and return the result.\n"
            "- Being the coordinator does not stop you answering "
            "directly. Delegation is a last resort, not the default.\n"
            "\n"
            "Request triage — classify BEFORE acting:\n"
            "- First decide what the request actually needs.\n"
            "- If you can answer it directly (your data sources, skills, "
            "or presets), just do that and reply. Do NOT create a "
            "project or task for questions, lookups, quick chats, or a "
            "single skill/preset job — return the answer itself.\n"
            "- Treat it as project work ONLY when the user explicitly asks "
            "to create/start/track a project, or it is a genuine "
            "multi-step initiative that needs delegation and tracking.\n"
            "\n"
            "When (and only when) it is project work:\n"
            "- You are a top-level coordinator. Project creation is not a "
            "delegated task — call project_create first.\n"
            "- Use project_create_task to create trackable project "
            "tasks/subtasks before assigning agent work.\n"
            "- Use managed_agent_directory to discover available agents by "
            "role, then assign execution tasks to the best matching "
            "subordinate with managed_agent_assign_task and the relevant "
            "project_task_id.\n"
            "- Match work to the right role: information, news, research, "
            "and lookup requests go to an Information Officer/CIO — never "
            "to a project or workflow manager. Project/workflow managers "
            "own project setup and tracking, not information retrieval.\n"
            "- If no suitable subordinate exists, state the missing role "
            "clearly and keep the project/task record updated yourself."
        )
    if "project manager" in role_key or "workflow manager" in role_key:
        return (
            "Use your own capabilities FIRST:\n"
            "- Use your connected data sources (via knowledge_search), "
            "skills, and presets to answer directly. Never claim you lack "
            "access to a topic without first checking knowledge_search "
            "when a relevant data source or skill is configured for you.\n"
            "\n"
            "Request triage — classify BEFORE acting:\n"
            "- If you can answer directly or via a skill/preset, just "
            "reply. Do NOT create a project or task for questions, quick "
            "chats, or a single skill/preset job.\n"
            "- Only when the user explicitly asks for a project, or it is "
            "a genuine multi-step initiative:\n"
            "  - Use project_create for new projects.\n"
            "  - Use project_create_task for trackable tasks and "
            "subtasks.\n"
            "  - Assign agent work only after a project task exists, "
            "passing its project_task_id into managed_agent_assign_task."
        )
    is_information_officer = (
        "information officer" in role_key
        or role_key == "cio"
        or "research" in role_key
        or "analyst" in role_key
        or "intelligence" in role_key
    )
    if is_information_officer:
        return (
            "You are the information/research authority. Answer "
            "information, news, research, monitoring, and lookup requests "
            "DIRECTLY and yourself.\n"
            "- knowledge_search is your primary tool — it covers your "
            "connected data sources (News/RSS, Hacker News, email, "
            "calendar, drive). Always call it before saying you lack "
            "access to any topic.\n"
            "- Synthesize the retrieved results into a concise, sourced "
            "answer. Do NOT paste the raw search output back — summarize "
            "the key points and include links where available.\n"
            "\n"
            "Request triage — classify BEFORE acting:\n"
            "- News, current events, lookups, and research questions are "
            "YOUR job: answer directly via knowledge_search/skills. NEVER "
            "create a project or task for these, and never delegate them "
            "to a project or workflow manager.\n"
            "- Treat it as project work ONLY when the user explicitly "
            "asks to create/start/track a project, or it is a genuine "
            "multi-step initiative; only then use project_create / "
            "project_create_task."
        )
    # Generic default — every other (or unspecified) role still gets
    # baseline triage so no agent routes a simple question into a project.
    return (
        "Use your own capabilities FIRST:\n"
        "- You have connected data sources, skills, and presets. Use them "
        "to answer directly. Query your knowledge with knowledge_search "
        "(it covers your connected data sources — e.g. News/RSS, Hacker "
        "News, email, calendar, drive) and run any skill or preset "
        "configured for you.\n"
        "- NEVER claim you 'do not have access' to news, current events, "
        "or any topic without first calling knowledge_search. If a "
        "relevant data source or skill is configured for you, you DO have "
        "access — use it and return the result.\n"
        "\n"
        "Request triage — classify BEFORE acting:\n"
        "- Decide what the request actually needs, then act once. If you "
        "can answer it directly (your data sources, skills, or presets), "
        "just do that and reply.\n"
        "- Do NOT create a project or task for questions, lookups, quick "
        "chats, or a single skill/preset job — return the answer itself. "
        "This is an interactive chat: prefer a direct answer over routing "
        "or delegation.\n"
        "- Treat it as project work ONLY when the user explicitly asks "
        "to create/start/track a project, or it is a genuine multi-step "
        "initiative; only then use project_create / project_create_task."
    )


def _build_managed_system_prompt(agent_record: Dict[str, Any]) -> str:
    config = agent_record.get("config", {}) or {}
    parts: List[str] = []
    system_prompt = str(config.get("system_prompt", "") or "").strip()
    instruction = str(config.get("instruction", "") or "").strip()
    if system_prompt:
        parts.append(system_prompt)
    if instruction and instruction != system_prompt:
        parts.append(f"Agent instruction:\n{instruction}")
    role_guidance = _role_guidance(agent_record)
    if role_guidance:
        parts.append(role_guidance)
    return "\n\n".join(parts)


_AGENT_TASK_COMPLETION_TOOLS = {
    "project_create",
    "project_create_task",
}


def _tool_calls_completed_agent_task(
    tool_calls: Optional[List[Dict[str, Any]]],
) -> bool:
    if not tool_calls:
        return False
    return any(
        call.get("tool") in _AGENT_TASK_COMPLETION_TOOLS
        and call.get("success", False)
        for call in tool_calls
    )


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
        if (
            hasattr(self._manager, "has_open_linked_task")
            and self._manager.has_open_linked_task(agent_id)
            and hasattr(self._manager, "has_runnable_task")
            and not self._manager.has_runnable_task(agent_id)
        ):
            raise ValueError(
                "Agent has linked work, but every open task is scheduled "
                "for a future start date/time."
            )

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
        self._project_writeback(agent_record, phase="start", summary=user_content)
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
        if (
            not had_error
            and _tool_calls_completed_agent_task(tool_calls)
        ):
            self._complete_linked_agent_task(
                agent_id,
                note="Completed by successful project setup tool execution.",
            )
        self._project_writeback(
            agent_record,
            phase="finish",
            summary=response_text,
            error=had_error,
        )
        if self._bus is not None:
            try:
                event_type = (
                    EventType.AGENT_TICK_ERROR
                    if had_error
                    else EventType.AGENT_TICK_END
                )
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

    # ── Project-task writeback (Mission Control) ──────────────────

    def _linked_project_task(self, agent_id: str) -> Optional[Dict[str, Any]]:
        """The agent's most relevant linked agent-task (active > recent)."""
        try:
            if hasattr(self._manager, "list_runnable_tasks"):
                tasks = self._manager.list_runnable_tasks(agent_id)
            else:
                tasks = self._manager.list_tasks(agent_id)
        except Exception:
            return None
        for status in ("active", "pending"):
            for t in tasks:
                if t.get("status") == status and t.get("project_task_id"):
                    return t
        for t in tasks:
            if t.get("project_task_id"):
                return t
        return None

    def _complete_linked_agent_task(self, agent_id: str, *, note: str) -> None:
        """Mark the current linked agent-task complete after deterministic work.

        The model can always call managed_agent_update_task itself. This
        fallback covers deterministic one-shot work such as project_create,
        where the tool result proves the assigned setup task is done.
        """
        try:
            task = self._linked_project_task(agent_id)
            if not task or task.get("status") == "completed":
                return
            progress = dict(task.get("progress") or {})
            progress["note"] = note
            self._manager.update_task(
                task["id"],
                status="completed",
                progress=progress,
            )
        except Exception:
            logger.exception("Failed to complete linked task for %s", agent_id)

    def _project_writeback(
        self,
        agent_record: Dict[str, Any],
        *,
        phase: str,
        summary: str = "",
        error: bool = False,
    ) -> None:
        """Mirror a run into its linked project task (best-effort).

        Role-gated via :mod:`openjarvis.projects.authz`: a note is added
        when allowed (all tiers), and status/percent is changed only when
        the agent may update the task (manager any; worker its own task).
        On success of a leaf task with no subtasks owned by the agent the
        task is completed; otherwise it is only nudged to In Progress so
        we never over-claim rolled-up progress. Never raises into the run.
        """
        try:
            link = self._linked_project_task(agent_record["id"])
            if not link or not link.get("project_task_id"):
                return
            ptid = str(link["project_task_id"])
            ps = self._manager._project_store()
            ptask = ps.get_task(ptid)
            if ptask is None:
                return

            from openjarvis.projects import authz

            agent_name = str(agent_record.get("name") or agent_record["id"])
            if authz.can(agent_record, "note.add", ptask):
                if phase == "start":
                    content = (
                        f"Agent '{agent_name}' started a run: "
                        f"{summary[:200]}"
                    )
                    ntype = "Agent"
                elif error:
                    content = (
                        f"Agent '{agent_name}' run failed: {summary[:300]}"
                    )
                    ntype = "Blocker"
                else:
                    content = (
                        f"Agent '{agent_name}' completed a run: "
                        f"{summary[:300]}"
                    )
                    ntype = "Agent"
                ps.add_note(
                    ptid, author=agent_name, content=content, type=ntype
                )

            if not authz.can(agent_record, "task.update", ptask):
                return
            updates: Dict[str, Any] = {}
            current = str(ptask.get("status") or "")
            nudge = ("", "Backlog", "Planning", "To Do")
            if phase == "start":
                if current in nudge:
                    updates["status"] = "In Progress"
            elif error:
                updates["status"] = "Blocked"
            else:
                subtasks = [
                    t
                    for t in ps.list_tasks(ptask["project_id"])
                    if t.get("parent_task_id") == ptid
                ]
                if not subtasks:
                    updates["status"] = "Done"
                    updates["percent_complete"] = 100
                elif current in nudge:
                    updates["status"] = "In Progress"
            if updates:
                ps.update_task(ptid, **updates)
        except Exception:
            logger.exception(
                "Project writeback (%s) failed for agent %s",
                phase,
                agent_record.get("id"),
            )

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
        model = (
            config.get("model")
            or getattr(self._engine, "_model", "")
            or self._default_model
        )
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
            system_prompt=_build_managed_system_prompt(agent_record),
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
        system_prompt = _build_managed_system_prompt(agent_record)
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
            tool_calls_raw = (
                result.get("tool_calls", []) if isinstance(result, dict) else []
            )

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
                    logger.exception(
                        "Managed agent tool execution failed for %s",
                        tool_name,
                    )
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
                    "Write the best final answer you can from the completed "
                    "tool results. "
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
