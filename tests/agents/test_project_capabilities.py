from __future__ import annotations

from openjarvis.agents.capabilities import effective_agent_tool_names


def test_chief_orchestrator_gets_project_tools():
    tools = effective_agent_tool_names(
        {
            "id": "chief",
            "name": "Chief",
            "org_role": "Chief Orchestrator",
            "agent_type": "monitor_operative",
            "config": {},
        }
    )

    assert "project_create" in tools
    assert "project_create_task" in tools
    assert "project_list" in tools
    assert "managed_agent_directory" in tools
    assert "managed_agent_assign_task" in tools


def test_developer_does_not_get_project_creation_tools_by_default():
    tools = effective_agent_tool_names(
        {
            "id": "dev",
            "name": "Developer",
            "org_role": "Developer",
            "agent_type": "monitor_operative",
            "config": {},
        }
    )

    assert "managed_agent_directory" in tools
    assert "project_create" not in tools
