"""Tools for discovering and delegating to other managed agents."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from openjarvis.core.registry import ToolRegistry
from openjarvis.core.types import ToolResult
from openjarvis.server.managed_agent_runtime import get_managed_agent_context
from openjarvis.tools._stubs import BaseTool, ToolSpec


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
        note = str(progress.get("note", "") or "").strip()
        if note:
            parts.append(f"progress_note={_truncate(note, 160)}")
        else:
            parts.append(f"progress={_truncate(str(progress), 120)}")
    if findings:
        preview = "; ".join(
            _truncate(
                str(
                    finding.get("summary")
                    if isinstance(finding, dict)
                    else finding
                ),
                80,
            )
            for finding in findings[:2]
        )
        if preview:
            parts.append(f"findings={preview}")
        else:
            parts.append(f"findings={len(findings)}")
    return " | ".join(parts)


def _collect_descendant_ids(manager: Any, agent_id: str) -> set[str]:
    seen: set[str] = set()
    stack = [agent_id]
    while stack:
        current = stack.pop()
        for candidate in manager.list_agents():
            candidate_id = str(candidate.get("id", "")).strip()
            if not candidate_id or candidate_id in seen:
                continue
            if str(candidate.get("manager_agent_id", "")).strip() == current:
                seen.add(candidate_id)
                stack.append(candidate_id)
    return seen


def _can_inspect_agent(ctx: Any, target_id: str) -> bool:
    current_id = str(ctx.current_agent_id or "").strip()
    target_id = str(target_id or "").strip()
    if not current_id or not target_id:
        return False
    if current_id == target_id:
        return True
    return target_id in _collect_descendant_ids(ctx.manager, current_id)


def _format_message(message: Dict[str, Any]) -> str:
    tool_calls = message.get("tool_calls") or []
    tool_summary = ""
    if tool_calls:
        names = ", ".join(str(entry.get("tool", "")) for entry in tool_calls[:5] if entry.get("tool"))
        if names:
            tool_summary = f" | tool_calls={names}"
    return " | ".join(
        [
            f"id={message.get('id', '')}",
            f"direction={message.get('direction', 'unknown')}",
            f"status={message.get('status', 'unknown')}",
            f"mode={message.get('mode', 'unknown')}",
            f"content={_truncate(str(message.get('content', '')), 200)}",
        ]
    ) + tool_summary


def _format_learning_log(entry: Dict[str, Any]) -> str:
    parts = [
        f"id={entry.get('id', '')}",
        f"event_type={entry.get('event_type', 'unknown')}",
    ]
    description = str(entry.get("description", "") or "").strip()
    if description:
        parts.append(f"description={_truncate(description, 180)}")
    data = entry.get("data") or {}
    if data:
        parts.append(f"data={_truncate(str(data), 120)}")
    return " | ".join(parts)


def _build_task_assignment_message(
    task: Dict[str, Any],
    *,
    assignee_name: str,
    assigner_name: str,
) -> str:
    description = str(task.get("description", "") or "").strip()
    status = str(task.get("status", "pending") or "pending")
    task_id = str(task.get("id", "") or "").strip()
    return (
        f"You have been assigned a persistent task by {assigner_name}.\n"
        f"Task ID: {task_id}\n"
        f"Assignee: {assignee_name}\n"
        f"Status: {status}\n"
        f"Task: {description}\n\n"
        "Start working on this now. If you make progress, use managed_agent_update_task "
        "to update the task status, progress, and findings. Reply with your immediate "
        "plan, status, or deliverable."
    )


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
                "up in that agent's task list. Provide project_task_id when "
                "known; otherwise the work is routed into Unassigned Work."
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
                    "project_task_id": {
                        "type": "string",
                        "description": (
                            "ID of the project task or subtask this "
                            "work belongs to (from the projects workspace). "
                            "If omitted, Jarvis creates a trackable child "
                            "task under Unassigned Work."
                        ),
                    },
                    "status": {
                        "type": "string",
                        "description": "Optional initial status.",
                        "enum": ["pending", "active", "completed", "failed"],
                    },
                    "start_now": {
                        "type": "boolean",
                        "description": (
                            "When true, immediately notify the assignee and start a "
                            "delegated execution turn so the agent begins work now. "
                            "Defaults to true."
                        ),
                    },
                },
                "required": [
                    "agent_name_or_id",
                    "description",
                ],
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

        try:
            task = ctx.manager.create_task(
                target["id"],
                description=str(params.get("description", "")),
                status=str(params.get("status", "pending") or "pending"),
                assigned_by_agent_id=ctx.current_agent_id,
                project_task_id=str(params.get("project_task_id", "") or "")
                or None,
                project_id=str(params.get("project_id", "") or "") or None,
            )
        except ValueError as exc:
            return ToolResult(
                tool_name=self.spec.name,
                success=False,
                content=(
                    f"Cannot delegate: {exc} Use a valid 'project_task_id' "
                    "or omit it so the task is routed to Unassigned Work."
                ),
            )
        target_name = str(target.get("name", target["id"]))
        assigner = ctx.manager.get_agent(ctx.current_agent_id)
        assigner_name = str(
            (assigner or {}).get("name", ctx.current_agent_id) or ctx.current_agent_id
        )
        start_now = bool(params.get("start_now", True))
        initial_response = ""
        if start_now:
            visited = tuple(ctx.visited_agent_ids) + (ctx.current_agent_id,)
            if target["id"] in visited:
                initial_response = (
                    "Immediate kickoff skipped because it would create a delegation loop."
                )
            elif len(visited) >= 6:
                initial_response = (
                    "Immediate kickoff skipped because the delegation depth limit was reached."
                )
            else:
                kickoff_message = _build_task_assignment_message(
                    task,
                    assignee_name=target_name,
                    assigner_name=assigner_name,
                )
                initial_response = ctx.runtime.run(
                    str(target["id"]),
                    kickoff_message,
                    parent_agent_id=ctx.current_agent_id,
                    visited_agent_ids=visited,
                )
        content = f"Assigned task to {target_name}: {_format_task(task, ctx.manager)}"
        if initial_response:
            content += f"\nInitial response from {target_name}: {initial_response}"
        return ToolResult(
            tool_name=self.spec.name,
            success=True,
            content=content,
            metadata={
                "task_id": task["id"],
                "agent_id": target["id"],
                "started": start_now,
                "initial_response": initial_response,
            },
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


@ToolRegistry.register("managed_agent_inspect")
class ManagedAgentInspectTool(BaseTool):
    """Inspect a managed agent's recent state, tasks, and history."""

    tool_id = "managed_agent_inspect"

    def __init__(self, context: Any = None) -> None:
        self._bound_context = context

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="managed_agent_inspect",
            description=(
                "Inspect a managed agent's current state, recent tasks, recent messages, "
                "and learning log. Agents may inspect themselves and their subordinate tree."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "agent_name_or_id": {
                        "type": "string",
                        "description": "The target agent's ID or name.",
                    },
                    "include_messages": {
                        "type": "boolean",
                        "description": "Include recent message history. Defaults to true.",
                    },
                    "include_learning_log": {
                        "type": "boolean",
                        "description": "Include recent learning/execution log entries. Defaults to true.",
                    },
                    "task_limit": {
                        "type": "integer",
                        "description": "Maximum number of tasks to include. Defaults to 10.",
                    },
                    "message_limit": {
                        "type": "integer",
                        "description": "Maximum number of messages to include. Defaults to 8.",
                    },
                    "learning_limit": {
                        "type": "integer",
                        "description": "Maximum number of learning-log entries to include. Defaults to 8.",
                    },
                },
                "required": ["agent_name_or_id"],
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

        current = ctx.manager.get_agent(ctx.current_agent_id)
        target_label = str(params.get("agent_name_or_id", "") or "").strip()
        target = None
        if current and (
            current["id"] == target_label
            or str(current.get("name", "")).strip().casefold() == target_label.casefold()
        ):
            target = current
        else:
            target, error = _resolve_agent(
                ctx.manager,
                target_label,
                current_agent_id="__no-self-block__",
            )
            if target is None:
                return ToolResult(
                    tool_name=self.spec.name,
                    success=False,
                    content=error,
                )

        if not _can_inspect_agent(ctx, str(target["id"])):
            return ToolResult(
                tool_name=self.spec.name,
                success=False,
                content=(
                    "Access denied. Agents may inspect themselves and their subordinate tree only."
                ),
            )

        include_messages = bool(params.get("include_messages", True))
        include_learning = bool(params.get("include_learning_log", True))
        task_limit = max(1, min(int(params.get("task_limit", 10) or 10), 25))
        message_limit = max(1, min(int(params.get("message_limit", 8) or 8), 25))
        learning_limit = max(1, min(int(params.get("learning_limit", 8) or 8), 25))

        agent_id = str(target["id"])
        tasks = ctx.manager.list_tasks(agent_id)[:task_limit]
        messages = ctx.manager.list_messages(agent_id, limit=message_limit) if include_messages else []
        learning_log = (
            ctx.manager.list_learning_log(agent_id, limit=learning_limit)
            if include_learning
            else []
        )
        direct_reports = [
            agent
            for agent in ctx.manager.list_agents()
            if str(agent.get("manager_agent_id", "")).strip() == agent_id
        ]
        config = target.get("config", {}) or {}

        sections = [
            "Agent overview:",
            " | ".join(
                [
                    f"id={agent_id}",
                    f"name={target.get('name', agent_id)}",
                    f"role={str(target.get('org_role', '')).strip() or 'Unassigned'}",
                    f"status={target.get('status', 'unknown')}",
                    f"type={target.get('agent_type', 'unknown')}",
                    f"manager={str(target.get('manager_agent_id', '')).strip() or 'top-level'}",
                    f"direct_reports={len(direct_reports)}",
                    f"current_activity={_truncate(str(target.get('current_activity', '') or ''), 120) or '(none)'}",
                ]
            ),
        ]
        summary_memory = str(target.get("summary_memory", "") or "").strip()
        if summary_memory:
            sections.append("Summary memory:\n" + _truncate(summary_memory, 400))

        sections.append(
            "Recent tasks:\n"
            + (
                "\n".join(_format_task(task, ctx.manager) for task in tasks)
                if tasks
                else "No tasks found."
            )
        )

        if include_messages:
            sections.append(
                "Recent messages:\n"
                + (
                    "\n".join(_format_message(message) for message in messages)
                    if messages
                    else "No messages found."
                )
            )

        if include_learning:
            sections.append(
                "Recent learning log:\n"
                + (
                    "\n".join(_format_learning_log(entry) for entry in learning_log)
                    if learning_log
                    else "No learning-log entries found."
                )
            )

        tools = config.get("tools") or []
        if tools:
            sections.append("Configured tools:\n" + ", ".join(str(tool) for tool in tools))

        return ToolResult(
            tool_name=self.spec.name,
            success=True,
            content="\n\n".join(sections),
            metadata={
                "agent_id": agent_id,
                "task_count": len(tasks),
                "message_count": len(messages),
                "learning_log_count": len(learning_log),
            },
        )
