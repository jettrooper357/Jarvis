"""Bulk-import a numbered Markdown outline into a project."""

from __future__ import annotations

import re

from openjarvis.core.registry import ToolRegistry
from openjarvis.core.types import ToolResult
from openjarvis.tools._stubs import BaseTool, ToolSpec

_CATEGORY_RE = re.compile(r"^\s*(\d+)\.\s+(.+?)\s*$")
_TASK_RE = re.compile(r"^\s*\d+\.(\d+)(?:\.\w+)?\s+(.+?)\s*$")
_SUBTASK_RE = re.compile(r"^\s*[\*\-]\s+(.+?)\s*$")

# Prefixed-label grammar, the format users actually paste from notes apps:
#
#   Category: Project Initiation and Planning
#   Task: Define Product Foundation
#   SubTask: Confirm final product name
#
# Common typos are tolerated: "Catgory:" appears in the wild, and the
# label is case-insensitive. The label and value are separated by a
# colon (with optional dash / em-dash / bullet between value words).
_LABEL_CATEGORY_RE = re.compile(
    r"^\s*cat[ea]?gor(?:y|ies)\s*:\s*(.+?)\s*$",
    re.IGNORECASE,
)
_LABEL_TASK_RE = re.compile(
    r"^\s*task\s*:\s*(.+?)\s*$",
    re.IGNORECASE,
)
_LABEL_SUBTASK_RE = re.compile(
    r"^\s*sub[\s\-_]?task\s*:\s*(.+?)\s*$",
    re.IGNORECASE,
)


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

        # Prefixed-label grammar is checked first so a "Task: foo" line
        # doesn't accidentally fall through to the numbered TASK_RE.
        m = _LABEL_SUBTASK_RE.match(line)
        if m:
            if not categories:
                skipped += 1
                continue
            cat = categories[-1]
            if not cat["tasks"]:
                cat["tasks"].append({"title": "General", "subtasks": []})
            cat["tasks"][-1]["subtasks"].append(m.group(1).strip())
            continue
        m = _LABEL_TASK_RE.match(line)
        if m:
            if not categories:
                skipped += 1
                continue
            categories[-1]["tasks"].append(
                {"title": m.group(1).strip(), "subtasks": []}
            )
            continue
        m = _LABEL_CATEGORY_RE.match(line)
        if m:
            categories.append({"title": m.group(1).strip(), "tasks": []})
            continue

        # Numbered Markdown grammar (1. Category / 1.1 Task / * Subtask).
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


def import_outline(
    store,
    *,
    outline,
    project_id="",
    project_name="",
    create_if_missing=True,
):
    """Resolve the project, parse the outline, and create the rows.

    Returns ``{"success": bool, "content": str, "metadata": dict}``. This
    is the shared core behind both the ``project_import_outline`` tool and
    the managed-agent runtime's deterministic bulk-outline fast path, so a
    huge outline never has to be echoed back through the model as a tool
    argument.
    """
    text = str(outline or "").strip()
    if not text:
        return {
            "success": False,
            "content": "outline is required and must not be empty.",
            "metadata": {},
        }

    project, err = _resolve_project(
        store,
        str(project_id or "").strip(),
        str(project_name or "").strip(),
        bool(create_if_missing),
    )
    if err or project is None:
        return {
            "success": False,
            "content": err or "Could not resolve project.",
            "metadata": {},
        }

    categories, skipped = _parse_outline(text)
    if not categories:
        return {
            "success": False,
            "content": f"Parsed 0 categories ({skipped} lines skipped). Check format.",
            "metadata": {},
        }

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

    summary = (
        f"Imported into project {project['name']} (id={pid}): "
        f"{cat_count} categories, {task_count} tasks, "
        f"{subtask_count} subtasks. {skipped} lines skipped."
    )
    return {
        "success": True,
        "content": summary,
        "metadata": {
            "project_id": pid,
            "project_name": project["name"],
            "categories_created": cat_count,
            "tasks_created": task_count,
            "subtasks_created": subtask_count,
            "lines_skipped": skipped,
        },
    }


@ToolRegistry.register("project_import_outline")
class ProjectImportOutlineTool(BaseTool):
    """Bulk-import a numbered Markdown outline into a project."""

    tool_id = "project_import_outline"

    @property
    def spec(self):
        return ToolSpec(
            name="project_import_outline",
            description=(
                "Bulk-import a multi-level work breakdown into a project, "
                "creating Category, Task, and Subtask rows in ONE call. "
                "ALWAYS use this when the user pastes more than ~3 tasks "
                "or any multi-level breakdown of a project's work, even "
                "if they don't say 'import'. Do NOT call "
                "project_create_task in a loop for this input -- looping "
                "will exhaust the turn budget and produce no response. "
                "Two grammars are accepted: "
                "(1) Numbered Markdown -- 'N.' = Category, 'N.M' = Task, "
                "'* item' = Subtask. "
                "(2) Prefixed labels -- 'Category: <name>', "
                "'Task: <name>', 'SubTask: <name>' (case-insensitive; "
                "'Catgory:' typo is tolerated). Lines that don't match "
                "either grammar are skipped."
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
        outcome = import_outline(
            _project_store(),
            outline=params.get("outline"),
            project_id=params.get("project_id") or "",
            project_name=params.get("project_name") or "",
            create_if_missing=bool(params.get("create_if_missing", True)),
        )
        return ToolResult(
            tool_name=self.spec.name,
            success=outcome["success"],
            content=outcome["content"],
            metadata=outcome["metadata"] or None,
        )


__all__ = ["ProjectImportOutlineTool", "import_outline"]
