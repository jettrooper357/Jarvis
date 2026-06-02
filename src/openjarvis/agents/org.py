"""Default agent org blueprint + idempotent bootstrap.

The runtime org model (org_role / manager_agent_id / is_chief) lives in
``agents/manager.py``. This module defines the DEFAULT_ORG tree and an
idempotent orchestrator that instantiates it via
``AgentManager.create_from_template``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

# Org role names (used as managed_agents.org_role values).
CHIEF = "chief_orchestrator"
EXEC_ASSISTANT = "executive_assistant"
WORKFLOW_MANAGER = "workflow_manager"
CTO = "cto_architect"
KNOWLEDGE_MANAGER = "knowledge_manager"
LIFE_MANAGER = "life_manager"


@dataclass(slots=True)
class OrgRole:
    """One node in the default org blueprint."""

    template_id: str
    org_role: str
    name: str
    manager_role: str = ""
    is_chief: bool = False


# Ordered so every ``manager_role`` is defined by an EARLIER entry.
DEFAULT_ORG: List[OrgRole] = [
    # Chief
    OrgRole("chief_orchestrator", CHIEF, "Chief Orchestrator", "", True),
    # Managers
    OrgRole("executive_assistant", EXEC_ASSISTANT, "Executive Assistant", CHIEF),
    OrgRole("workflow_manager", WORKFLOW_MANAGER, "Workflow Manager", CHIEF),
    OrgRole("cto_architect", CTO, "CTO / Architect", CHIEF),
    OrgRole("knowledge_manager", KNOWLEDGE_MANAGER, "Knowledge Manager", CHIEF),
    OrgRole("life_manager", LIFE_MANAGER, "Life Manager", CHIEF),
    # Executive Assistant reports
    OrgRole("inbox_triager", "inbox_analyst", "Inbox Analyst", EXEC_ASSISTANT),
    OrgRole("calendar_agent", "calendar", "Calendar Agent", EXEC_ASSISTANT),
    OrgRole("followup_agent", "followup", "Follow-Up Agent", EXEC_ASSISTANT),
    # Workflow Manager reports
    OrgRole(
        "project_assistant", "project_planner", "Project Planner", WORKFLOW_MANAGER
    ),
    OrgRole("timeline_agent", "timeline", "Timeline Agent", WORKFLOW_MANAGER),
    OrgRole("risk_analyst", "risk_analyst", "Risk Analyst", WORKFLOW_MANAGER),
    # CTO reports
    OrgRole("code_developer", "code_developer", "Code Developer", CTO),
    OrgRole("code_reviewer", "code_reviewer", "Code Reviewer", CTO),
    OrgRole("test_engineer", "test_engineer", "Test Engineer", CTO),
    OrgRole("sql_engineer", "sql_engineer", "SQL Engineer", CTO),
    OrgRole("deployment_agent", "deployment", "Deployment Agent", CTO),
    # Knowledge Manager reports
    OrgRole(
        "doc_indexing_agent",
        "document_indexing",
        "Document Indexing Agent",
        KNOWLEDGE_MANAGER,
    ),
    OrgRole("research_monitor", "research", "Research Agent", KNOWLEDGE_MANAGER),
    OrgRole("notes_agent", "notes", "Notes Agent", KNOWLEDGE_MANAGER),
    # Life Manager reports
    OrgRole("sermon_study", "church", "Church / Sermon Agent", LIFE_MANAGER),
    OrgRole("health_routine", "health", "Health Routine Agent", LIFE_MANAGER),
    OrgRole("finance_reminder", "finance", "Finance Reminder Agent", LIFE_MANAGER),
    OrgRole("learning_coach", "personal_goals", "Personal Goals Agent", LIFE_MANAGER),
]


def _by_org_role(manager: Any) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for agent in manager.list_agents():
        role = str(agent.get("org_role") or "").strip()
        if role and role not in out:
            out[role] = agent
    return out


def bootstrap_default_org(
    manager: Any,
    *,
    blueprint: Optional[List[OrgRole]] = None,
) -> Dict[str, Any]:
    """Instantiate the default org, idempotently.

    For each blueprint role, skip if an agent with that ``org_role`` already
    exists; otherwise create it from its template with the resolved
    ``manager_agent_id``. Returns ``{created, skipped, chief_id}``.
    """
    roles = blueprint if blueprint is not None else DEFAULT_ORG
    existing = _by_org_role(manager)
    created: List[str] = []
    skipped: List[str] = []
    role_to_id: Dict[str, str] = {r: a["id"] for r, a in existing.items()}
    chief_id: Optional[str] = None

    for role in roles:
        if role.org_role in existing:
            skipped.append(role.org_role)
            if role.is_chief:
                chief_id = existing[role.org_role]["id"]
            continue
        manager_id = role_to_id.get(role.manager_role) if role.manager_role else None
        agent = manager.create_from_template(
            role.template_id,
            name=role.name,
            org_role=role.org_role,
            manager_agent_id=manager_id,
        )
        role_to_id[role.org_role] = agent["id"]
        created.append(role.org_role)
        if role.is_chief:
            chief_id = agent["id"]

    if chief_id is not None:
        manager.set_chief_agent(chief_id)
    return {"created": created, "skipped": skipped, "chief_id": chief_id}


def build_org_tree(manager: Any) -> Optional[Dict[str, Any]]:
    """Return the hierarchy as a nested dict rooted at the chief, or None."""
    chief = manager.get_chief_agent()
    if chief is None:
        return None
    agents = manager.list_agents()
    children: Dict[str, List[Dict[str, Any]]] = {}
    for a in agents:
        mgr_id = a.get("manager_agent_id")
        if mgr_id:
            children.setdefault(mgr_id, []).append(a)

    def _node(agent: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "id": agent["id"],
            "name": agent.get("name", ""),
            "org_role": agent.get("org_role", ""),
            "is_chief": bool(agent.get("is_chief")),
            "reports": [_node(c) for c in children.get(agent["id"], [])],
        }

    return _node(chief)
