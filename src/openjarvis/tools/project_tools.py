"""Project-management tools for managed agents."""

from __future__ import annotations

from datetime import datetime, timedelta
import re
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


def _default_task_dates() -> Dict[str, str]:
    start = datetime.now().date()
    return {
        "start_date": start.isoformat(),
        "due_date": (start + timedelta(days=1)).isoformat(),
    }


def _parse_iso_date(value: Any):
    """Return a date from an ISO-ish string, or None if unparseable."""
    text = str(value or "").strip()
    if not text:
        return None
    # Accept date or datetime ISO strings.
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        try:
            return datetime.strptime(text, "%Y-%m-%d").date()
        except ValueError:
            return None


def _sanitize_task_dates(
    fields: Dict[str, Any],
    *,
    start_key: str = "start_date",
    end_key: str = "due_date",
) -> None:
    """Replace LLM-supplied dates that are before today with the real date.

    Older model snapshots (2024-cutoff) frequently emit dates from the
    prior year even with a "today is ..." system-prompt anchor. Clamping
    any past start/end to today / today+1 keeps Mission Control project
    tasks anchored to the wall clock. When both start and end were
    supplied and end >= start, the duration is preserved.
    """
    today = datetime.now().date()
    start = _parse_iso_date(fields.get(start_key))
    end = _parse_iso_date(fields.get(end_key))

    if start and start < today:
        if end and end >= start:
            duration = end - start
            fields[start_key] = today.isoformat()
            fields[end_key] = (today + duration).isoformat()
            return
        fields[start_key] = today.isoformat()

    if end:
        new_start = _parse_iso_date(fields.get(start_key)) or today
        if end < new_start:
            fields[end_key] = (new_start + timedelta(days=1)).isoformat()


def _clean_task_title(title: str) -> str:
    text = str(title or "").strip()
    # Strip delegation-prompt artifacts. The chief's delegation message has
    # the shape "...GOAL: <goal>\nACCEPTANCE CRITERIA: ...\nBUDGET: ...".
    # If a subordinate pastes any of that block into the title field, we
    # extract just the goal phrase by (1) jumping past GOAL: if present,
    # then (2) truncating at the next section header.
    goal_match = re.search(r"\bgoal\s*:\s*", text, flags=re.IGNORECASE)
    if goal_match:
        text = text[goal_match.end():].strip(" .,:;-\"'") or text
    section_split = re.split(
        r"\s*(?:acceptance\s+criteria|budget|deliverables?|depends_on|"
        r"task_id|tools_allowed|budget_max_turns|when\s+you\s+finish)\s*:",
        text,
        maxsplit=1,
        flags=re.IGNORECASE,
    )
    if len(section_split) > 1:
        text = section_split[0].strip(" .,:;-\"'") or text
    # If the title is still a long multi-sentence blob, keep only the
    # first sentence.
    if len(text) > 120:
        first_sentence = re.split(r"(?<=[.!?])\s+", text, maxsplit=1)[0]
        if first_sentence and len(first_sentence) < len(text):
            text = first_sentence.strip(" .,:;-\"'") or text
    text = re.sub(
        r"\s+(?:to|in|on|under)\s+(?:the\s+)?"
        r"[A-Za-z0-9 &'._-]+?\s+project\.?$",
        "",
        text,
        flags=re.IGNORECASE,
    ).strip(" .,:;-\"'")
    song_match = re.search(
        r"\b(?:called|named|titled)\s+['\"]?(?P<title>[^'\"]+?)['\"]?$",
        text,
        flags=re.IGNORECASE,
    )
    if song_match and re.search(
        r"\b(?:song|single|track)\b",
        text,
        flags=re.IGNORECASE,
    ):
        return song_match.group("title").strip(" .,:;-\"'") or text
    task_match = re.search(
        r"\btask\s+(?:to|for)\s+(?P<title>.+)$",
        text,
        flags=re.IGNORECASE,
    )
    if task_match:
        return task_match.group("title").strip(" .,:;-\"'") or text
    return text


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
    working_folder = str(project.get("working_folder", "") or "").strip()
    if working_folder:
        parts.append(f"working_folder={working_folder}")
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
    category = str(task.get("category", "") or "").strip()
    if category:
        parts.append(f"category={category}")
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
                    "working_folder": {
                        "type": "string",
                        "description": (
                            "Filesystem path where agents do work for "
                            "this project. Auto-created if missing. "
                            "All file/shell/git tool calls for this "
                            "project are sandboxed to this directory."
                        ),
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
                "working_folder",
            )
            if params.get(key) is not None
        }
        _sanitize_task_dates(fields, start_key="start_date", end_key="target_date")
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
                    "category": {
                        "type": "string",
                        "description": (
                            "Optional category label grouping this task with "
                            "others under the same name in the project."
                        ),
                    },
                    "status": {"type": "string", "description": "Task status."},
                    "start_date": {
                        "type": "string",
                        "description": "Optional ISO start date.",
                    },
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
        title = _clean_task_title(str(params.get("title", "") or "").strip())
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
                "category",
                "status",
                "assigned_to",
                "owner",
                "priority",
                "start_date",
                "due_date",
            )
            if params.get(key) is not None
        }
        fields["title"] = title
        defaults = _default_task_dates()
        fields.setdefault("start_date", defaults["start_date"])
        fields.setdefault("due_date", defaults["due_date"])
        _sanitize_task_dates(fields)
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


@ToolRegistry.register("project_update")
class ProjectUpdateTool(BaseTool):
    """Update fields on an existing project (incl. working folder)."""

    tool_id = "project_update"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="project_update",
            description=(
                "Update fields on an existing project. Use this to set "
                "or change the working_folder where agents do work for "
                "the project, or to update name/description/status/etc."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "project_id": {
                        "type": "string",
                        "description": "Project ID to update.",
                    },
                    "name": {"type": "string", "description": "New name."},
                    "description": {
                        "type": "string",
                        "description": "New description.",
                    },
                    "owner": {"type": "string", "description": "Owner."},
                    "status": {"type": "string", "description": "Status."},
                    "tags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Tags.",
                    },
                    "team": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Team members.",
                    },
                    "start_date": {
                        "type": "string",
                        "description": "ISO start date.",
                    },
                    "target_date": {
                        "type": "string",
                        "description": "ISO target date.",
                    },
                    "working_folder": {
                        "type": "string",
                        "description": (
                            "Filesystem path where agents do work for "
                            "this project. Auto-created if missing. "
                            "Empty string clears it."
                        ),
                    },
                },
                "required": ["project_id"],
            },
            category="project",
        )

    def execute(self, **params: Any) -> ToolResult:
        project_id = str(params.get("project_id", "") or "").strip()
        if not project_id:
            return ToolResult(
                tool_name=self.spec.name,
                success=False,
                content="project_id is required.",
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
                "working_folder",
            )
            if params.get(key) is not None
        }
        if not fields:
            return ToolResult(
                tool_name=self.spec.name,
                success=False,
                content="No fields to update were provided.",
            )
        _sanitize_task_dates(fields, start_key="start_date", end_key="target_date")
        try:
            project = _project_store().update_project(project_id, **fields)
        except KeyError:
            return ToolResult(
                tool_name=self.spec.name,
                success=False,
                content=f"Project not found: {project_id}",
            )
        return ToolResult(
            tool_name=self.spec.name,
            success=True,
            content=f"Updated project: {_format_project(project)}",
            metadata={"project_id": project["id"], "project": project},
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


def _format_milestone(milestone: Dict[str, Any]) -> str:
    return (
        f"id={milestone.get('id', '')} | "
        f"name={milestone.get('name', '')} | "
        f"date={milestone.get('date', '') or 'TBD'} | "
        f"done={bool(milestone.get('done'))}"
    )


@ToolRegistry.register("project_update_task")
class ProjectUpdateTaskTool(BaseTool):
    """Edit an existing project task or subtask."""

    tool_id = "project_update_task"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="project_update_task",
            description=(
                "Update fields on an existing task or subtask (status, "
                "percent_complete, assignee, priority, dates, category, "
                "etc.). Use this to record progress when given an update."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "task_id": {"type": "string", "description": "Task ID."},
                    "title": {"type": "string", "description": "New title."},
                    "description": {
                        "type": "string",
                        "description": "New description.",
                    },
                    "status": {"type": "string", "description": "New status."},
                    "category": {
                        "type": "string",
                        "description": "Category label ('' clears it).",
                    },
                    "priority": {"type": "string", "description": "Priority."},
                    "assigned_to": {
                        "type": "string",
                        "description": "Assignee name.",
                    },
                    "owner": {"type": "string", "description": "Owner."},
                    "percent_complete": {
                        "type": "integer",
                        "description": "Completion percent 0-100.",
                    },
                    "start_date": {
                        "type": "string",
                        "description": "ISO start date.",
                    },
                    "due_date": {
                        "type": "string",
                        "description": "ISO due date.",
                    },
                    "parent_task_id": {
                        "type": "string",
                        "description": "Re-parent under this task ID.",
                    },
                    "type": {"type": "string", "description": "Task type."},
                },
                "required": ["task_id"],
            },
            category="project",
        )

    def execute(self, **params: Any) -> ToolResult:
        task_id = str(params.get("task_id", "") or "").strip()
        if not task_id:
            return ToolResult(
                tool_name=self.spec.name,
                success=False,
                content="task_id is required.",
            )
        fields = {
            key: params.get(key)
            for key in (
                "title",
                "description",
                "status",
                "category",
                "priority",
                "assigned_to",
                "owner",
                "percent_complete",
                "start_date",
                "due_date",
                "parent_task_id",
                "type",
            )
            if params.get(key) is not None
        }
        if not fields:
            return ToolResult(
                tool_name=self.spec.name,
                success=False,
                content="No fields to update were provided.",
            )
        _sanitize_task_dates(fields)
        try:
            task = _project_store().update_task(task_id, **fields)
        except KeyError:
            return ToolResult(
                tool_name=self.spec.name,
                success=False,
                content=f"Task not found: {task_id}",
            )
        return ToolResult(
            tool_name=self.spec.name,
            success=True,
            content=f"Updated task: {_format_task(task)}",
            metadata={"project_task_id": task["id"], "task": task},
        )


@ToolRegistry.register("project_delete_task")
class ProjectDeleteTaskTool(BaseTool):
    """Delete a project task or subtask (cascades to its subtasks/notes)."""

    tool_id = "project_delete_task"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="project_delete_task",
            description=(
                "Delete a task or subtask. This also removes its subtasks "
                "and notes. Use deliberately — it cannot be undone."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "task_id": {"type": "string", "description": "Task ID."},
                },
                "required": ["task_id"],
            },
            category="project",
        )

    def execute(self, **params: Any) -> ToolResult:
        task_id = str(params.get("task_id", "") or "").strip()
        if not task_id:
            return ToolResult(
                tool_name=self.spec.name,
                success=False,
                content="task_id is required.",
            )
        store = _project_store()
        if store.get_task(task_id) is None:
            return ToolResult(
                tool_name=self.spec.name,
                success=False,
                content=f"Task not found: {task_id}",
            )
        store.delete_task(task_id)
        return ToolResult(
            tool_name=self.spec.name,
            success=True,
            content=f"Deleted task: {task_id}",
            metadata={"deleted_task_id": task_id},
        )


@ToolRegistry.register("project_add_note")
class ProjectAddNoteTool(BaseTool):
    """Add a progress/status note to a task."""

    tool_id = "project_add_note"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="project_add_note",
            description=(
                "Add a note to a task. Use this to log progress, decisions, "
                "or status whenever you are given an update on the work."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "task_id": {"type": "string", "description": "Task ID."},
                    "content": {
                        "type": "string",
                        "description": "The note text.",
                    },
                    "author": {
                        "type": "string",
                        "description": "Optional note author.",
                    },
                    "type": {
                        "type": "string",
                        "description": "Note type (e.g. Comment, Update).",
                    },
                },
                "required": ["task_id", "content"],
            },
            category="project",
        )

    def execute(self, **params: Any) -> ToolResult:
        task_id = str(params.get("task_id", "") or "").strip()
        content = str(params.get("content", "") or "").strip()
        if not task_id or not content:
            return ToolResult(
                tool_name=self.spec.name,
                success=False,
                content="task_id and content are required.",
            )
        fields = {
            key: params.get(key)
            for key in ("content", "author", "type")
            if params.get(key) is not None
        }
        try:
            note = _project_store().add_note(task_id, **fields)
        except KeyError:
            return ToolResult(
                tool_name=self.spec.name,
                success=False,
                content=f"Task not found: {task_id}",
            )
        return ToolResult(
            tool_name=self.spec.name,
            success=True,
            content=f"Added note to task {task_id}.",
            metadata={"task_id": task_id, "note_id": note["id"], "note": note},
        )


@ToolRegistry.register("project_add_milestone")
class ProjectAddMilestoneTool(BaseTool):
    """Add a milestone to a project."""

    tool_id = "project_add_milestone"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="project_add_milestone",
            description="Add a milestone (name + optional date) to a project.",
            parameters={
                "type": "object",
                "properties": {
                    "project_id": {
                        "type": "string",
                        "description": "Project ID.",
                    },
                    "name": {
                        "type": "string",
                        "description": "Milestone name.",
                    },
                    "date": {
                        "type": "string",
                        "description": "Optional target date.",
                    },
                },
                "required": ["project_id", "name"],
            },
            category="project",
        )

    def execute(self, **params: Any) -> ToolResult:
        project_id = str(params.get("project_id", "") or "").strip()
        name = str(params.get("name", "") or "").strip()
        if not project_id or not name:
            return ToolResult(
                tool_name=self.spec.name,
                success=False,
                content="project_id and name are required.",
            )
        try:
            milestone = _project_store().add_milestone(
                project_id, name, str(params.get("date", "") or "")
            )
        except KeyError:
            return ToolResult(
                tool_name=self.spec.name,
                success=False,
                content=f"Project not found: {project_id}",
            )
        return ToolResult(
            tool_name=self.spec.name,
            success=True,
            content=f"Added milestone: {_format_milestone(milestone)}",
            metadata={"project_id": project_id, "milestone": milestone},
        )


@ToolRegistry.register("project_update_milestone")
class ProjectUpdateMilestoneTool(BaseTool):
    """Edit a project milestone (name, date, or done state)."""

    tool_id = "project_update_milestone"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="project_update_milestone",
            description="Update a milestone's name, date, or done status.",
            parameters={
                "type": "object",
                "properties": {
                    "project_id": {
                        "type": "string",
                        "description": "Project ID.",
                    },
                    "milestone_id": {
                        "type": "string",
                        "description": "Milestone ID.",
                    },
                    "name": {"type": "string", "description": "New name."},
                    "date": {"type": "string", "description": "New date."},
                    "done": {
                        "type": "boolean",
                        "description": "Mark complete/incomplete.",
                    },
                },
                "required": ["project_id", "milestone_id"],
            },
            category="project",
        )

    def execute(self, **params: Any) -> ToolResult:
        project_id = str(params.get("project_id", "") or "").strip()
        milestone_id = str(params.get("milestone_id", "") or "").strip()
        if not project_id or not milestone_id:
            return ToolResult(
                tool_name=self.spec.name,
                success=False,
                content="project_id and milestone_id are required.",
            )
        fields = {
            key: params.get(key)
            for key in ("name", "date", "done")
            if params.get(key) is not None
        }
        try:
            milestone = _project_store().update_milestone(
                project_id, milestone_id, **fields
            )
        except KeyError as exc:
            missing = str(exc).strip("'")
            target = (
                f"Project not found: {project_id}"
                if missing == project_id
                else f"Milestone not found: {milestone_id}"
            )
            return ToolResult(
                tool_name=self.spec.name, success=False, content=target
            )
        return ToolResult(
            tool_name=self.spec.name,
            success=True,
            content=f"Updated milestone: {_format_milestone(milestone)}",
            metadata={"project_id": project_id, "milestone": milestone},
        )


@ToolRegistry.register("project_delete_milestone")
class ProjectDeleteMilestoneTool(BaseTool):
    """Delete a project milestone."""

    tool_id = "project_delete_milestone"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="project_delete_milestone",
            description="Remove a milestone from a project.",
            parameters={
                "type": "object",
                "properties": {
                    "project_id": {
                        "type": "string",
                        "description": "Project ID.",
                    },
                    "milestone_id": {
                        "type": "string",
                        "description": "Milestone ID.",
                    },
                },
                "required": ["project_id", "milestone_id"],
            },
            category="project",
        )

    def execute(self, **params: Any) -> ToolResult:
        project_id = str(params.get("project_id", "") or "").strip()
        milestone_id = str(params.get("milestone_id", "") or "").strip()
        if not project_id or not milestone_id:
            return ToolResult(
                tool_name=self.spec.name,
                success=False,
                content="project_id and milestone_id are required.",
            )
        try:
            _project_store().delete_milestone(project_id, milestone_id)
        except KeyError as exc:
            missing = str(exc).strip("'")
            target = (
                f"Project not found: {project_id}"
                if missing == project_id
                else f"Milestone not found: {milestone_id}"
            )
            return ToolResult(
                tool_name=self.spec.name, success=False, content=target
            )
        return ToolResult(
            tool_name=self.spec.name,
            success=True,
            content=f"Deleted milestone: {milestone_id}",
            metadata={
                "project_id": project_id,
                "deleted_milestone_id": milestone_id,
            },
        )


@ToolRegistry.register("project_add_category")
class ProjectAddCategoryTool(BaseTool):
    """Create a category label on a project."""

    tool_id = "project_add_category"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="project_add_category",
            description=(
                "Create a category on a project so tasks/subtasks can be "
                "grouped under it. The category shows even before any task "
                "uses it."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "project_id": {
                        "type": "string",
                        "description": "Project ID.",
                    },
                    "name": {
                        "type": "string",
                        "description": "Category name.",
                    },
                },
                "required": ["project_id", "name"],
            },
            category="project",
        )

    def execute(self, **params: Any) -> ToolResult:
        project_id = str(params.get("project_id", "") or "").strip()
        name = str(params.get("name", "") or "").strip()
        if not project_id or not name:
            return ToolResult(
                tool_name=self.spec.name,
                success=False,
                content="project_id and name are required.",
            )
        try:
            categories = _project_store().add_category(project_id, name)
        except KeyError:
            return ToolResult(
                tool_name=self.spec.name,
                success=False,
                content=f"Project not found: {project_id}",
            )
        return ToolResult(
            tool_name=self.spec.name,
            success=True,
            content=f"Categories for {project_id}: {', '.join(categories)}",
            metadata={"project_id": project_id, "categories": categories},
        )


@ToolRegistry.register("project_rename_category")
class ProjectRenameCategoryTool(BaseTool):
    """Rename a category (propagates to all tasks using it)."""

    tool_id = "project_rename_category"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="project_rename_category",
            description=(
                "Rename a project category. Every task/subtask currently "
                "labelled with the old name is moved to the new name."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "project_id": {
                        "type": "string",
                        "description": "Project ID.",
                    },
                    "old_name": {
                        "type": "string",
                        "description": "Existing category name.",
                    },
                    "new_name": {
                        "type": "string",
                        "description": "New category name.",
                    },
                },
                "required": ["project_id", "old_name", "new_name"],
            },
            category="project",
        )

    def execute(self, **params: Any) -> ToolResult:
        project_id = str(params.get("project_id", "") or "").strip()
        old_name = str(params.get("old_name", "") or "").strip()
        new_name = str(params.get("new_name", "") or "").strip()
        if not project_id or not old_name or not new_name:
            return ToolResult(
                tool_name=self.spec.name,
                success=False,
                content="project_id, old_name and new_name are required.",
            )
        try:
            categories = _project_store().rename_category(
                project_id, old_name, new_name
            )
        except KeyError:
            return ToolResult(
                tool_name=self.spec.name,
                success=False,
                content=f"Project not found: {project_id}",
            )
        return ToolResult(
            tool_name=self.spec.name,
            success=True,
            content=(
                f"Renamed category '{old_name}' to '{new_name}'. "
                f"Categories: {', '.join(categories)}"
            ),
            metadata={"project_id": project_id, "categories": categories},
        )


@ToolRegistry.register("project_delete_category")
class ProjectDeleteCategoryTool(BaseTool):
    """Delete a category; tasks using it become uncategorized."""

    tool_id = "project_delete_category"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="project_delete_category",
            description=(
                "Delete a project category. Tasks/subtasks that used it "
                "become uncategorized; the tasks themselves are kept."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "project_id": {
                        "type": "string",
                        "description": "Project ID.",
                    },
                    "name": {
                        "type": "string",
                        "description": "Category name to delete.",
                    },
                },
                "required": ["project_id", "name"],
            },
            category="project",
        )

    def execute(self, **params: Any) -> ToolResult:
        project_id = str(params.get("project_id", "") or "").strip()
        name = str(params.get("name", "") or "").strip()
        if not project_id or not name:
            return ToolResult(
                tool_name=self.spec.name,
                success=False,
                content="project_id and name are required.",
            )
        try:
            categories = _project_store().delete_category(project_id, name)
        except KeyError:
            return ToolResult(
                tool_name=self.spec.name,
                success=False,
                content=f"Project not found: {project_id}",
            )
        return ToolResult(
            tool_name=self.spec.name,
            success=True,
            content=(
                f"Deleted category '{name}'. "
                f"Remaining: {', '.join(categories) or '(none)'}"
            ),
            metadata={"project_id": project_id, "categories": categories},
        )
