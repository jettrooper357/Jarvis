"""Tools for discovering and delegating to other managed agents."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from openjarvis.core.registry import ToolRegistry
from openjarvis.core.types import ToolResult
from openjarvis.tools._stubs import BaseTool, ToolSpec

from openjarvis.server.managed_agent_runtime import get_managed_agent_context


def _truncate(value: str, limit: int = 180) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def _resolve_agent(
    manager: Any,
    agent_name_or_id: str,
    *,
    current_agent_id: str,
) -> tuple[Optional[Dict[str, Any]], str]:
    target = str(agent_name_or_id or "").strip()
    if not target:
        return None, "An agent name or ID is required."

    direct = manager.get_agent(target)
    if direct is not None:
        if direct["id"] == current_agent_id:
            return None, "Refusing to delegate to the same agent."
        return direct, ""

    agents = manager.list_agents()
    exact = [
        agent
        for agent in agents
        if str(agent.get("name", "")).strip().casefold() == target.casefold()
        and agent.get("id") != current_agent_id
    ]
    if len(exact) == 1:
        return exact[0], ""

    fuzzy = [
        agent
        for agent in agents
        if target.casefold() in str(agent.get("name", "")).strip().casefold()
        and agent.get("id") != current_agent_id
    ]
    if len(fuzzy) == 1:
        return fuzzy[0], ""
    if len(exact) > 1 or len(fuzzy) > 1:
        candidates = exact or fuzzy
        names = ", ".join(
            f"{agent.get('name', agent.get('id'))} ({agent.get('id')})"
            for agent in candidates[:8]
        )
        return None, f"Multiple agents matched '{target}': {names}"
    return None, f"No managed agent matched '{target}'."


def _format_task(task: Dict[str, Any], manager: Any) -> str:
    assigned_by = ""
    assigned_by_id = str(task.get("assigned_by_agent_id", "") or "").strip()
    if assigned_by_id:
        assigned_by_agent = manager.get_agent(assigned_by_id)
        assigned_by = (
            assigned_by_agent.get("name", assigned_by_id)
            if assigned_by_agent is not None
            else assigned_by_id
        )
    progress = task.get("progress") or {}
    findings = task.get("findings") or []
    parts = [
        f"id={task.get('id', '')}",
        f"agent_id={task.get('agent_id', '')}",
        f"status={task.get('status', 'unknown')}",
        f"description={_truncate(str(task.get('description', '')), 200)}",
    ]
    if assigned_by:
        parts.append(f"assigned_by={assigned_by}")
    if progress:
        parts.append(f"progress={_truncate(str(progress), 120)}")
    if findings:
        parts.append(f"findings={len(findings)}")
    return " | ".join(parts)


@ToolRegistry.register("managed_agent_directory")
class ManagedAgentDirectoryTool(BaseTool):
    """List other managed agents so a coordinator can delegate intelligently."""

    tool_id = "managed_agent_directory"

    def __init__(self, context: Any = None) -> None:
        self._bound_context = context

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="managed_agent_directory",
            description=(
                "List the other managed agents available for delegation, including "
                "their IDs, names, types, status, and short instruction excerpts."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "include_archived": {
                        "type": "boolean",
                        "description": "Include archived or paused agents too.",
                    }
                },
            },
            category="agent",
        )

    def execute(self, **params: Any) -> ToolResult:
        ctx = self._bound_context or get_managed_agent_context()
        if ctx is None:
            return ToolResult(
                tool_name=self.spec.name,
                success=False,
                content="Managed-agent context is not available.",
            )
        include_archived = bool(params.get("include_archived", False))
        lines: List[str] = []
        for agent in ctx.manager.list_agents():
            agent_id = str(agent.get("id", ""))
            if not agent_id or agent_id == ctx.current_agent_id:
                continue
            status = str(agent.get("status", "unknown"))
            if not include_archived and status in {"archived", "paused"}:
                continue
            config = agent.get("config", {}) or {}
            instruction = config.get("instruction") or config.get("system_prompt") or ""
            org_role = str(agent.get("org_role", "")).strip() or "Unassigned"
            reports_to = str(agent.get("manager_agent_id", "")).strip() or "top-level"
            lines.append(
                " | ".join(
                    [
                        f"id={agent_id}",
                        f"name={agent.get('name', agent_id)}",
                        f"role={org_role}",
                        f"reports_to={reports_to}",
                        f"type={agent.get('agent_type', '') or 'unknown'}",
                        f"status={status}",
                        f"instruction={_truncate(str(instruction), 140) or '(none)'}",
                    ]
                )
            )
        if not lines:
            return ToolResult(
                tool_name=self.spec.name,
                success=True,
                content="No other managed agents are currently available.",
            )
        return ToolResult(
            tool_name=self.spec.name,
            success=True,
            content="Available managed agents:\n" + "\n".join(lines),
        )


@ToolRegistry.register("managed_agent_delegate")
class ManagedAgentDelegateTool(BaseTool):
    """Delegate a subtask to another managed agent and return its reply."""

    tool_id = "managed_agent_delegate"

    def __init__(self, context: Any = None) -> None:
        self._bound_context = context

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="managed_agent_delegate",
            description=(
                "Ask another managed agent to handle a focused subtask and return "
                "that agent's reply. Use the directory tool first when you need to "
                "discover the right agent."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "agent_name_or_id": {
                        "type": "string",
                        "description": "The target agent's ID or human-readable name.",
                    },
                    "message": {
                        "type": "string",
                        "description": "The exact subtask or question to send.",
                    },
                },
                "required": ["agent_name_or_id", "message"],
            },
            category="agent",
        )

    def execute(self, **params: Any) -> ToolResult:
        ctx = self._bound_context or get_managed_agent_context()
        if ctx is None:
            return ToolResult(
                tool_name=self.spec.name,
                success=False,
                content="Managed-agent context is not available.",
            )

        target, error = _resolve_agent(
            ctx.manager,
            str(params.get("agent_name_or_id", "")),
            current_agent_id=ctx.current_agent_id,
        )
        if target is None:
            return ToolResult(
                tool_name=self.spec.name,
                success=False,
                content=error,
            )

        target_id = str(target["id"])
        visited = tuple(ctx.visited_agent_ids) + (ctx.current_agent_id,)
        if target_id in visited:
            return ToolResult(
                tool_name=self.spec.name,
                success=False,
                content=(
                    "Delegation loop blocked. "
                    f"Visited agents: {', '.join(visited)}"
                ),
            )
        if len(visited) >= 6:
            return ToolResult(
                tool_name=self.spec.name,
                success=False,
                content="Delegation depth limit reached.",
            )

        reply = ctx.runtime.run(
            target_id,
            str(params.get("message", "")),
            parent_agent_id=ctx.current_agent_id,
            visited_agent_ids=visited,
        )
        target_name = str(target.get("name", target_id))
        return ToolResult(
            tool_name=self.spec.name,
            success=True,
            content=f"Response from {target_name} ({target_id}): {reply}",
            metadata={"agent_id": target_id, "agent_name": target_name},
        )


@ToolRegistry.register("managed_agent_message")
class ManagedAgentMessageTool(BaseTool):
    """Send an internal message to another managed agent and return the reply."""

    tool_id = "managed_agent_message"

    def __init__(self, context: Any = None) -> None:
        self._bound_context = context

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="managed_agent_message",
            description=(
                "Send a direct internal message to another managed agent and "
                "return that agent's reply."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "agent_name_or_id": {
                        "type": "string",
                        "description": "The target agent's ID or name.",
                    },
                    "message": {
                        "type": "string",
                        "description": "The message or question to send.",
                    },
                },
                "required": ["agent_name_or_id", "message"],
            },
            category="agent",
        )

    def execute(self, **params: Any) -> ToolResult:
        return ManagedAgentDelegateTool(context=self._bound_context).execute(**params)


@ToolRegistry.register("managed_agent_assign_task")
class ManagedAgentAssignTaskTool(BaseTool):
    """Assign a persistent task to another managed agent."""

    tool_id = "managed_agent_assign_task"

    def __init__(self, context: Any = None) -> None:
        self._bound_context = context

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="managed_agent_assign_task",
            description=(
                "Create a persistent task for another managed agent so it shows "
                "up in that agent's task list."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "agent_name_or_id": {
                        "type": "string",
                        "description": "The target agent's ID or name.",
                    },
                    "description": {
                        "type": "string",
                        "description": "The task to assign.",
                    },
                    "status": {
                        "type": "string",
                        "description": "Optional initial status.",
                        "enum": ["pending", "active", "completed", "failed"],
                    },
                },
                "required": ["agent_name_or_id", "description"],
            },
            category="agent",
        )

    def execute(self, **params: Any) -> ToolResult:
        ctx = self._bound_context or get_managed_agent_context()
        if ctx is None:
            return ToolResult(
                tool_name=self.spec.name,
                success=False,
                content="Managed-agent context is not available.",
            )

        target, error = _resolve_agent(
            ctx.manager,
            str(params.get("agent_name_or_id", "")),
            current_agent_id=ctx.current_agent_id,
        )
        if target is None:
            return ToolResult(
                tool_name=self.spec.name,
                success=False,
                content=error,
            )

        task = ctx.manager.create_task(
            target["id"],
            description=str(params.get("description", "")),
            status=str(params.get("status", "pending") or "pending"),
            assigned_by_agent_id=ctx.current_agent_id,
        )
        target_name = str(target.get("name", target["id"]))
        return ToolResult(
            tool_name=self.spec.name,
            success=True,
            content=f"Assigned task to {target_name}: {_format_task(task, ctx.manager)}",
            metadata={"task_id": task["id"], "agent_id": target["id"]},
        )


@ToolRegistry.register("managed_agent_list_tasks")
class ManagedAgentListTasksTool(BaseTool):
    """List persistent tasks for a managed agent."""

    tool_id = "managed_agent_list_tasks"

    def __init__(self, context: Any = None) -> None:
        self._bound_context = context

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="managed_agent_list_tasks",
            description=(
                "List persistent tasks for the current agent or another managed agent."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "agent_name_or_id": {
                        "type": "string",
                        "description": "Optional target agent ID or name. Defaults to the current agent.",
                    },
                    "status": {
                        "type": "string",
                        "description": "Optional task status filter.",
                        "enum": ["pending", "active", "completed", "failed"],
                    },
                },
            },
            category="agent",
        )

    def execute(self, **params: Any) -> ToolResult:
        ctx = self._bound_context or get_managed_agent_context()
        if ctx is None:
            return ToolResult(
                tool_name=self.spec.name,
                success=False,
                content="Managed-agent context is not available.",
            )

        target = ctx.manager.get_agent(ctx.current_agent_id)
        target_label = "current agent"
        agent_name_or_id = str(params.get("agent_name_or_id", "") or "").strip()
        if agent_name_or_id:
            resolved, error = _resolve_agent(
                ctx.manager,
                agent_name_or_id,
                current_agent_id="__no-self-block__",
            )
            if resolved is None:
                current = ctx.manager.get_agent(ctx.current_agent_id)
                if current and (
                    current["id"] == agent_name_or_id
                    or str(current.get("name", "")).strip().casefold()
                    == agent_name_or_id.casefold()
                ):
                    resolved = current
                else:
                    return ToolResult(
                        tool_name=self.spec.name,
                        success=False,
                        content=error,
                    )
            target = resolved
            target_label = str(resolved.get("name", resolved["id"]))

        if target is None:
            return ToolResult(
                tool_name=self.spec.name,
                success=False,
                content="Current agent could not be resolved.",
            )

        tasks = ctx.manager.list_tasks(
            target["id"],
            status=str(params.get("status", "") or "") or None,
        )
        if not tasks:
            return ToolResult(
                tool_name=self.spec.name,
                success=True,
                content=f"No tasks found for {target_label}.",
            )
        return ToolResult(
            tool_name=self.spec.name,
            success=True,
            content=(
                f"Tasks for {target_label}:\n"
                + "\n".join(_format_task(task, ctx.manager) for task in tasks)
            ),
        )


@ToolRegistry.register("managed_agent_update_task")
class ManagedAgentUpdateTaskTool(BaseTool):
    """Update a managed-agent task status or progress."""

    tool_id = "managed_agent_update_task"

    def __init__(self, context: Any = None) -> None:
        self._bound_context = context

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="managed_agent_update_task",
            description=(
                "Update the status, progress, or findings for a persistent managed-agent task."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "task_id": {
                        "type": "string",
                        "description": "The task ID to update.",
                    },
                    "status": {
                        "type": "string",
                        "description": "Optional new status.",
                        "enum": ["pending", "active", "completed", "failed"],
                    },
                    "progress_note": {
                        "type": "string",
                        "description": "Optional human-readable progress note.",
                    },
                    "findings": {
                        "type": "array",
                        "description": "Optional list of findings to attach to the task.",
                    },
                },
                "required": ["task_id"],
            },
            category="agent",
        )

    def execute(self, **params: Any) -> ToolResult:
        ctx = self._bound_context or get_managed_agent_context()
        if ctx is None:
            return ToolResult(
                tool_name=self.spec.name,
                success=False,
                content="Managed-agent context is not available.",
            )

        task_id = str(params.get("task_id", "")).strip()
        if not task_id:
            return ToolResult(
                tool_name=self.spec.name,
                success=False,
                content="task_id is required.",
            )

        task = ctx.manager._get_task(task_id)
        if task is None:
            return ToolResult(
                tool_name=self.spec.name,
                success=False,
                content=f"Task not found: {task_id}",
            )

        kwargs: Dict[str, Any] = {}
        if params.get("status") is not None:
            kwargs["status"] = str(params.get("status", "")).strip() or "pending"
        if params.get("progress_note") is not None:
            existing_progress = task.get("progress") or {}
            next_progress = dict(existing_progress)
            next_progress["note"] = str(params.get("progress_note", ""))
            kwargs["progress"] = next_progress
        if params.get("findings") is not None:
            kwargs["findings"] = params.get("findings")
        if not kwargs:
            return ToolResult(
                tool_name=self.spec.name,
                success=False,
                content="Provide at least one of: status, progress_note, findings.",
            )
        updated = ctx.manager.update_task(task_id, **kwargs)
        return ToolResult(
            tool_name=self.spec.name,
            success=True,
            content=f"Updated task: {_format_task(updated, ctx.manager)}",
            metadata={"task_id": task_id, "agent_id": updated["agent_id"]},
        )
