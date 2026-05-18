"""Project-management tools for managed agents."""

from __future__ import annotations

from typing import Any, Dict, List

from openjarvis.core.registry import ToolRegistry
from openjarvis.core.types import ToolResult
from openjarvis.tools._stubs import BaseTool, ToolSpec


def _project_store() -> Any:
    from openjarvis.projects.store import ProjectStore

    return ProjectStore()


def _truncate(value: str, limit: int = 220) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def _format_project(project: Dict[str, Any]) -> str:
    parts = [
        f"id={project.get('id', '')}",
        f"name={project.get('name', '')}",
        f"status={project.get('status', '')}",
        f"progress={project.get('progress', 0)}%",
    ]
    owner = str(project.get("owner", "") or "").strip()
    if owner:
        parts.append(f"owner={owner}")
    description = str(project.get("description", "") or "").strip()
    if description:
        parts.append(f"description={_truncate(description)}")
    return " | ".join(parts)


def _format_task(task: Dict[str, Any]) -> str:
    parts = [
        f"id={task.get('id', '')}",
        f"project_id={task.get('project_id', '')}",
        f"title={task.get('title', '')}",
        f"status={task.get('status', '')}",
        f"type={task.get('type', '')}",
        f"priority={task.get('priority', '')}",
        f"complete={task.get('percent_complete', 0)}%",
    ]
    parent = str(task.get("parent_task_id", "") or "").strip()
    if parent:
        parts.append(f"parent_task_id={parent}")
    assigned = str(task.get("assigned_to", "") or "").strip()
    if assigned:
        parts.append(f"assigned_to={assigned}")
    description = str(task.get("description", "") or "").strip()
    if description:
        parts.append(f"description={_truncate(description)}")
    return " | ".join(parts)


@ToolRegistry.register("project_create")
class ProjectCreateTool(BaseTool):
    """Create a project in the shared Mission Control workspace."""

    tool_id = "project_create"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="project_create",
            description=(
                "Create a new project in Mission Control. Use this directly "
                "when the user asks to create, start, or set up a project; "
                "do not use managed_agent_assign_task for initial project creation."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Project name.",
                    },
                    "description": {
                        "type": "string",
                        "description": "Optional project description or objective.",
                    },
                    "owner": {
                        "type": "string",
                        "description": "Optional project owner.",
                    },
                    "status": {
                        "type": "string",
                        "description": "Initial status.",
                    },
                    "tags": {
                        "type": "array",
                        "description": "Optional tags.",
                        "items": {"type": "string"},
                    },
                    "team": {
                        "type": "array",
                        "description": "Optional team member names.",
                        "items": {"type": "string"},
                    },
                    "start_date": {
                        "type": "string",
                        "description": "Optional ISO start date.",
                    },
                    "target_date": {
                        "type": "string",
                        "description": "Optional ISO target date.",
                    },
                },
                "required": ["name"],
            },
            category="project",
        )

    def execute(self, **params: Any) -> ToolResult:
        name = str(params.get("name", "") or "").strip()
        if not name:
            return ToolResult(
                tool_name=self.spec.name,
                success=False,
                content="Project name is required.",
            )
        fields = {
            key: params.get(key)
            for key in (
                "name",
                "description",
                "owner",
                "status",
                "tags",
                "team",
                "start_date",
                "target_date",
            )
            if params.get(key) is not None
        }
        project = _project_store().create_project(**fields)
        return ToolResult(
            tool_name=self.spec.name,
            success=True,
            content=f"Created project: {_format_project(project)}",
            metadata={"project_id": project["id"], "project": project},
        )


@ToolRegistry.register("project_create_task")
class ProjectCreateTaskTool(BaseTool):
    """Create a task or subtask under a project."""

    tool_id = "project_create_task"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="project_create_task",
            description=(
                "Create a project task or subtask. Use this before assigning "
                "agent work, because managed_agent_assign_task requires the "
                "resulting project_task_id."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "project_id": {"type": "string", "description": "Project ID."},
                    "title": {"type": "string", "description": "Task title."},
                    "description": {
                        "type": "string",
                        "description": "Optional task details.",
                    },
                    "parent_task_id": {
                        "type": "string",
                        "description": "Optional parent task ID for a subtask.",
                    },
                    "type": {"type": "string", "description": "Task type."},
                    "status": {"type": "string", "description": "Task status."},
                    "assigned_to": {
                        "type": "string",
                        "description": "Optional assignee name.",
                    },
                    "owner": {"type": "string", "description": "Optional owner."},
                    "priority": {"type": "string", "description": "Priority."},
                    "due_date": {
                        "type": "string",
                        "description": "Optional ISO due date.",
                    },
                },
                "required": ["project_id", "title"],
            },
            category="project",
        )

    def execute(self, **params: Any) -> ToolResult:
        project_id = str(params.get("project_id", "") or "").strip()
        title = str(params.get("title", "") or "").strip()
        if not project_id or not title:
            return ToolResult(
                tool_name=self.spec.name,
                success=False,
                content="project_id and title are required.",
            )
        fields = {
            key: params.get(key)
            for key in (
                "title",
                "description",
                "parent_task_id",
                "type",
                "status",
                "assigned_to",
                "owner",
                "priority",
                "due_date",
            )
            if params.get(key) is not None
        }
        try:
            task = _project_store().create_task(project_id, **fields)
        except KeyError:
            return ToolResult(
                tool_name=self.spec.name,
                success=False,
                content=f"Project not found: {project_id}",
            )
        return ToolResult(
            tool_name=self.spec.name,
            success=True,
            content=f"Created project task: {_format_task(task)}",
            metadata={
                "project_id": task["project_id"],
                "project_task_id": task["id"],
                "task": task,
            },
        )


@ToolRegistry.register("project_list")
class ProjectListTool(BaseTool):
    """List projects in the shared workspace."""

    tool_id = "project_list"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="project_list",
            description="List existing projects in Mission Control.",
            parameters={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Optional case-insensitive name filter.",
                    },
                    "include_tasks": {
                        "type": "boolean",
                        "description": (
                            "Include each project's tasks. Defaults to false."
                        ),
                    },
                },
            },
            category="project",
        )

    def execute(self, **params: Any) -> ToolResult:
        store = _project_store()
        query = str(params.get("query", "") or "").strip().casefold()
        include_tasks = bool(params.get("include_tasks", False))
        projects: List[Dict[str, Any]] = []
        for project in store.list_projects():
            if query and query not in str(project.get("name", "")).casefold():
                continue
            projects.append(project)
        if not projects:
            return ToolResult(
                tool_name=self.spec.name,
                success=True,
                content="No matching projects found.",
            )
        lines: List[str] = []
        for project in projects:
            lines.append(_format_project(project))
            if include_tasks:
                for task in store.list_tasks(project["id"]):
                    lines.append(f"  - {_format_task(task)}")
        return ToolResult(
            tool_name=self.spec.name,
            success=True,
            content="Projects:\n" + "\n".join(lines),
            metadata={"projects": projects},
        )
