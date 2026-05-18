"""Role-based authorization for project/task writes (Mission Control).

Agents act on the shared :class:`~openjarvis.projects.store.ProjectStore`
according to their org-chart role. There are three tiers, matched from a
managed agent's free-text ``org_role`` plus its position in the org chart
(an agent with no manager sits at the top and is treated as a manager):

* **manager**  — Project Management / Manager. Owns the plan: full project
  and task CRUD, (re)assignment, scheduling.
* **worker**   — Worker / Operative (the default). Executes assigned work:
  may update only the tasks assigned to it and create subtasks under its
  own task.
* **qa**       — Quality Assurance / QA Testing. Verifies work: read-only
  on structure, may add notes, pass/fail a task under test, and file bug
  subtasks under the task being tested. Cannot create/delete projects or
  reassign work.

The module is intentionally dependency-free (pure dict in / bool out) so it
can be reused by the API router, the agent runtime, and tests.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

ROLE_MANAGER = "manager"
ROLE_WORKER = "worker"
ROLE_QA = "qa"

# Keyword matching is function-first: a "QA Lead" is QA, not a manager.
_QA_KEYWORDS = ("qa", "quality", "test", "review")
_MANAGER_KEYWORDS = (
    "manager",
    "project manage",
    "pm",
    "director",
    "lead",
    "owner",
    "chief",
    "head",
)

# Actions an agent may attempt against the project store.
ACTIONS = (
    "project.create",
    "project.update",
    "project.delete",
    "task.create",
    "task.update",
    "task.delete",
    "task.reassign",
    "note.add",
    "qa.passfail",
    "qa.file_bug",
)


def classify(agent: Optional[Dict[str, Any]]) -> str:
    """Return the role tier for a managed-agent dict.

    Precedence: QA keywords > manager keywords / org-chart top > worker.
    A missing/empty agent defaults to ``worker`` (least privilege).
    """
    if not agent:
        return ROLE_WORKER
    role = str(agent.get("org_role") or "").strip().lower()
    if any(k in role for k in _QA_KEYWORDS):
        return ROLE_QA
    has_manager = bool(str(agent.get("manager_agent_id") or "").strip())
    if any(k in role for k in _MANAGER_KEYWORDS) or not has_manager:
        return ROLE_MANAGER
    return ROLE_WORKER


def _owns(agent: Dict[str, Any], project_task: Optional[Dict[str, Any]]) -> bool:
    """True when the project task is assigned to this agent (by id or name)."""
    if not project_task:
        return False
    assignee = str(project_task.get("assigned_to") or "").strip().lower()
    if not assignee:
        return False
    return assignee in {
        str(agent.get("id") or "").strip().lower(),
        str(agent.get("name") or "").strip().lower(),
    }


def can(
    agent: Optional[Dict[str, Any]],
    action: str,
    project_task: Optional[Dict[str, Any]] = None,
) -> bool:
    """Return whether ``agent`` may perform ``action``.

    ``project_task`` is the target project task/subtask dict (from
    ProjectStore) when the action concerns a specific task; it is used for
    ownership checks in the worker tier.
    """
    role = classify(agent)

    if role == ROLE_MANAGER:
        # Managers own the plan end to end.
        return action in ACTIONS

    if role == ROLE_QA:
        return action in ("note.add", "qa.passfail", "qa.file_bug")

    # worker (default, least privilege): only its own assigned task.
    if action == "note.add":
        return True
    if action in ("task.update", "task.create") and _owns(agent, project_task):
        # task.create here = a subtask under the agent's own task.
        return True
    return False


def authorize(
    agent: Optional[Dict[str, Any]],
    action: str,
    project_task: Optional[Dict[str, Any]] = None,
) -> None:
    """Raise :class:`PermissionError` if the action is not allowed."""
    if not can(agent, action, project_task):
        who = (agent or {}).get("name") or (agent or {}).get("id") or "agent"
        raise PermissionError(
            f"{who} (role tier '{classify(agent)}') is not permitted to "
            f"perform '{action}' on this project task."
        )


__all__ = [
    "ROLE_MANAGER",
    "ROLE_WORKER",
    "ROLE_QA",
    "ACTIONS",
    "classify",
    "can",
    "authorize",
]
