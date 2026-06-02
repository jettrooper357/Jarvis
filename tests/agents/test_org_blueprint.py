from __future__ import annotations

from openjarvis.agents.org import DEFAULT_ORG, OrgRole


def test_blueprint_is_dependency_ordered_single_chief():
    seen: set[str] = set()
    chiefs = [r for r in DEFAULT_ORG if r.is_chief]
    assert len(chiefs) == 1
    assert chiefs[0].manager_role == ""
    roles: set[str] = set()
    for r in DEFAULT_ORG:
        assert isinstance(r, OrgRole)
        assert r.org_role not in roles, f"duplicate org_role {r.org_role}"
        roles.add(r.org_role)
        if r.manager_role:
            assert r.manager_role in seen, (
                f"{r.org_role} reports to undefined-earlier {r.manager_role}"
            )
        seen.add(r.org_role)


def test_blueprint_has_five_managers_under_chief():
    chief = next(r for r in DEFAULT_ORG if r.is_chief)
    managers = [r for r in DEFAULT_ORG if r.manager_role == chief.org_role]
    assert len(managers) == 5


def test_every_template_id_resolves():
    from openjarvis.agents.library import list_templates

    template_ids = {t.get("id") for t in list_templates()}
    for r in DEFAULT_ORG:
        assert r.template_id in template_ids, f"missing template {r.template_id}"


def test_new_role_templates_have_org_role_and_schedule():
    from openjarvis.agents.library import list_templates

    by_id = {t["id"]: t for t in list_templates()}
    for tid in (
        "chief_orchestrator",
        "workflow_manager",
        "cto_architect",
        "knowledge_manager",
        "calendar_agent",
        "followup_agent",
        "timeline_agent",
        "risk_analyst",
        "code_developer",
        "test_engineer",
        "sql_engineer",
        "deployment_agent",
        "doc_indexing_agent",
        "notes_agent",
    ):
        assert tid in by_id, f"missing template {tid}"
        assert by_id[tid].get("org_role"), f"{tid} missing org_role"
        assert "schedule_type" in by_id[tid]
