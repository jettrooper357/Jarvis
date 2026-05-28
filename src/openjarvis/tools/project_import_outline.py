"""Bulk-import a numbered Markdown outline into a project."""

from __future__ import annotations

import re

from openjarvis.core.registry import ToolRegistry
from openjarvis.core.types import ToolResult
from openjarvis.tools._stubs import BaseTool, ToolSpec

_CATEGORY_RE = re.compile(r"^\s*(\d+)\.\s+(.+?)\s*$")
_TASK_RE = re.compile(r"^\s*\d+\.(\d+)(?:\.\w+)?\s+(.+?)\s*$")
_SUBTASK_RE = re.compile(r"^\s*[\*\-]\s+(.+?)\s*$")


def _project_store():
    from openjarvis.projects.store import ProjectStore
    return ProjectStore()


def _resolve_project(store, project_id, project_name, create_if_missing):
    if project_id:
        project = store.get_project(project_id)
        if project:
            return project, None
        return None, f"Project not found by id: {project_id}"
    if project_name:
        wanted = project_name.casefold()
        for project in store.list_projects():
            if str(project.get("name", "")).casefold() == wanted:
                return project, None
        if create_if_missing:
            project = store.create_project(name=project_name)
            return project, None
        return None, f"Project not found by name: {project_name}"
    return None, "project_id or project_name is required"


def _parse_outline(outline):
    categories = []
    skipped = 0
    for raw in outline.splitlines():
        line = raw.rstrip()
        stripped = line.strip()
        if not stripped or stripped in ("---", "***"):
            continue
        m = _TASK_RE.match(line)
        if m:
            if not categories:
                skipped += 1
                continue
            categories[-1]["tasks"].append(
                {"title": m.group(2).strip(), "subtasks": []}
            )
            continue
        m = _CATEGORY_RE.match(line)
        if m:
            categories.append({"title": m.group(2).strip(), "tasks": []})
            continue
        m = _SUBTASK_RE.match(line)
        if m:
            if not categories:
                skipped += 1
                continue
            cat = categories[-1]
            if not cat["tasks"]:
                cat["tasks"].append({"title": "General", "subtasks": []})
            cat["tasks"][-1]["subtasks"].append(m.group(1).strip())
            continue
        skipped += 1
    return categories, skipped


@ToolRegistry.register("project_import_outline")
class ProjectImportOutlineTool(BaseTool):
    """Bulk-import a numbered Markdown outline into a project."""

    tool_id = "project_import_outline"

    @property
    def spec(self):
        return ToolSpec(
            name="project_import_outline",
            description=(
                "Bulk-import a numbered Markdown outline into a project, "
                "creating Category, Task, and Subtask rows in one call. "
                "Use this when the user pastes a multi-level numbered "
                "work breakdown and asks to add it to a project. Do NOT "
                "call project_create_task in a loop for this input. "
                "Grammar: N. lines are Categories, N.M lines are Tasks "
                "under the preceding Category, and * lines are Subtasks "
                "under the preceding Task."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "outline": {
                        "type": "string",
                        "description": "The full multi-line outline text.",
                    },
                    "project_id": {
                        "type": "string",
                        "description": "Existing project ID.",
                    },
                    "project_name": {
                        "type": "string",
                        "description": "Project name for lookup or creation.",
                    },
                    "create_if_missing": {
                        "type": "boolean",
                        "description": (
                            "Create the project when project_name "
                            "does not match. Default true."
                        ),
                    },
                },
                "required": ["outline"],
            },
            category="project",
        )

    def execute(self, **params):
        outline = str(params.get("outline") or "").strip()
        if not outline:
            return ToolResult(
                tool_name=self.spec.name,
                success=False,
                content="outline is required and must not be empty.",
            )
        project_id = str(params.get("project_id") or "").strip()
        project_name = str(params.get("project_name") or "").strip()
        create_if_missing = bool(params.get("create_if_missing", True))

        store = _project_store()
        project, err = _resolve_project(
            store, project_id, project_name, create_if_missing
        )
        if err or project is None:
            return ToolResult(
                tool_name=self.spec.name,
                success=False,
                content=err or "Could not resolve project.",
            )

        categories, skipped = _parse_outline(outline)
        if not categories:
            return ToolResult(
                tool_name=self.spec.name,
                success=False,
                content=f"Parsed 0 categories ({skipped} lines skipped). Check format.",
            )

        pid = project["id"]
        cat_count = 0
        task_count = 0
        subtask_count = 0
        task_sort = 0
        for cat in categories:
            # Categories live in the project's ``categories`` JSON list, not
            # as task rows. Tasks reference them via ``tasks.category``.
            store.add_category(pid, cat["title"])
            cat_count += 1
            for task in cat["tasks"]:
                task_sort += 1
                task_row = store.create_task(
                    pid,
                    title=task["title"],
                    type="Task",
                    category=cat["title"],
                    sort_order=task_sort,
                )
                task_count += 1
                sub_sort = 0
                for sub_title in task["subtasks"]:
                    sub_sort += 1
                    store.create_task(
                        pid,
                        title=sub_title,
                        type="Subtask",
                        category=cat["title"],
                        parent_task_id=task_row["id"],
                        sort_order=sub_sort,
                    )
                    subtask_count += 1

        name = project["name"]
        summary = (
            f"Imported into project {name} (id={pid}): "
            f"{cat_count} categories, {task_count} tasks, "
            f"{subtask_count} subtasks. {skipped} lines skipped."
        )
        return ToolResult(
            tool_name=self.spec.name,
            success=True,
            content=summary,
            metadata={
                "project_id": pid,
                "categories_created": cat_count,
                "tasks_created": task_count,
                "subtasks_created": subtask_count,
                "lines_skipped": skipped,
            },
        )


__all__ = ["ProjectImportOutlineTool"]
