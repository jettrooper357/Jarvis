from __future__ import annotations

from openjarvis.server.managed_agent_runtime import _build_managed_system_prompt


def test_managed_system_prompt_includes_stored_instruction():
    prompt = _build_managed_system_prompt(
        {
            "id": "chief",
            "name": "Chief",
            "org_role": "Chief Orchestrator",
            "config": {
                "instruction": "Route work through the hierarchy.",
            },
        }
    )

    assert "Route work through the hierarchy." in prompt
    assert "Project creation is not a delegated task" in prompt
    assert "project_create first" in prompt
    # Capability rule: the agent must use its own data sources / skills
    # to answer, and must NOT refuse with "no access" before checking.
    assert "knowledge_search" in prompt
    assert 'do not have access' in prompt
    # Guardrail: simple chat / skill / preset requests must NOT be turned
    # into projects — the agent answers and replies instead.
    assert "Do NOT create a project or task" in prompt


def test_project_manager_prompt_has_skill_guardrail():
    prompt = _build_managed_system_prompt(
        {
            "id": "pm",
            "name": "PM",
            "org_role": "Project Manager",
            "config": {},
        }
    )

    assert "Do NOT create a project or task" in prompt
    assert "skill/preset" in prompt
    assert "knowledge_search" in prompt


def test_plain_agent_prompt_has_no_project_guidance():
    prompt = _build_managed_system_prompt(
        {
            "id": "worker",
            "name": "Worker",
            "config": {"system_prompt": "Be helpful."},
        }
    )

    assert prompt == "Be helpful."
    assert "project_create" not in prompt
