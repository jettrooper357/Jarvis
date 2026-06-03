from __future__ import annotations

from openjarvis.agents.manager import AgentManager
from openjarvis.projects.store import ProjectStore
from openjarvis.watchtower.service import WatchtowerService
from openjarvis.watchtower.store import WatchtowerStore
from openjarvis.watchtower.types import Priority, WatchtowerSettings


def test_normal_overdue_task_routes_to_chief_not_direct_user(tmp_path) -> None:
    project_store = ProjectStore(tmp_path / "projects.db")
    project = project_store.create_project(name="AutoFax", status="Active")
    project_store.create_task(
        project["id"],
        title="Finish SQL migration",
        status="In Progress",
        due_date="2026-01-01",
    )
    manager = AgentManager(db_path=str(tmp_path / "agents.db"))
    chief = manager.create_agent(name="Chief", org_role="chief")
    manager.set_chief_agent(chief["id"])
    store = WatchtowerStore(tmp_path / "watchtower.db")
    service = WatchtowerService(
        store=store,
        settings=WatchtowerSettings(telegram_enabled=False),
        project_store=project_store,
        agent_manager=manager,
        provider_config={"engine": "openai"},
        engine=object(),
    )

    result = service.scan_once()

    assert result["findings_detected"] == 1
    finding = store.list_findings()[0]
    assert finding.priority == Priority.HIGH
    routes = store.list_internal_routes()
    assert len(routes) == 1
    assert routes[0].to_agent_id == chief["id"]
    assert routes[0].route_type == "send_to_chief"
    assert store.list_findings()[0].notification_count == 0
    messages = manager.list_messages(chief["id"], include_all_sessions=True)
    assert "Watchtower-triggered internal route" in messages[0]["content"]
    assert service.local_ai_status == "rules_fallback"

    store.close()
    project_store.close()


def test_route_to_chief_api_helper_persists_route(tmp_path) -> None:
    manager = AgentManager(db_path=str(tmp_path / "agents.db"))
    chief = manager.create_agent(name="Chief", org_role="chief")
    manager.set_chief_agent(chief["id"])
    store = WatchtowerStore(tmp_path / "watchtower.db")
    finding = store.upsert_finding(
        finding_type="blocked_agent",
        entity_type="agent",
        entity_id="a1",
        priority=Priority.HIGH,
        reason="blocked",
    )
    service = WatchtowerService(
        store=store,
        settings=WatchtowerSettings(telegram_enabled=False),
        agent_manager=manager,
    )

    route = service.route_to_chief(finding.finding_id)

    assert route["to_agent_id"] == chief["id"]
    assert route["status"] == "sent"
    store.close()
