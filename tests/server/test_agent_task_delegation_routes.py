from __future__ import annotations

import pytest

pytest.importorskip("fastapi", reason="openjarvis[server] not installed")

from fastapi import FastAPI
from fastapi.testclient import TestClient

from openjarvis.agents.manager import AgentManager
from openjarvis.projects.store import ProjectStore
from openjarvis.server.agent_manager_routes import create_agent_manager_router


def test_agent_tasks_can_include_delegated_work(tmp_path):
    ps = ProjectStore(tmp_path / "projects.db")
    manager = AgentManager(str(tmp_path / "agents.db"), project_store=ps)
    app = FastAPI()
    for router in create_agent_manager_router(manager):
        app.include_router(router)

    try:
        boss = manager.create_agent(name="PM", org_role="Project Manager")
        worker = manager.create_agent(
            name="Worker",
            org_role="Developer",
            manager_agent_id=boss["id"],
        )
        project = ps.create_project(name="P")
        project_task = ps.create_task(project["id"], title="Build")
        manager.create_task(
            worker["id"],
            description="Implement feature",
            assigned_by_agent_id=boss["id"],
            project_task_id=project_task["id"],
            status="active",
        )

        client = TestClient(app)
        plain = client.get(f"/v1/managed-agents/{boss['id']}/tasks").json()
        assert plain["tasks"] == []

        delegated = client.get(
            f"/v1/managed-agents/{boss['id']}/tasks?include_delegated=true"
        ).json()
        assert len(delegated["tasks"]) == 1
        assert delegated["tasks"][0]["agent_id"] == worker["id"]
        assert delegated["tasks"][0]["assigned_by_agent_id"] == boss["id"]
    finally:
        manager.close()
        ps.close()
