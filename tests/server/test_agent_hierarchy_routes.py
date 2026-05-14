from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

pytest.importorskip("fastapi", reason="openjarvis[server] not installed")

from fastapi import FastAPI
from fastapi.testclient import TestClient

from openjarvis.agents.manager import AgentManager
from openjarvis.server.agent_manager_routes import create_agent_manager_router


@pytest.fixture
def client():
    with tempfile.TemporaryDirectory() as tmpdir:
        manager = AgentManager(db_path=str(Path(tmpdir) / "agents.db"))
        app = FastAPI()
        for router in create_agent_manager_router(manager):
            app.include_router(router)
        try:
            yield TestClient(app)
        finally:
            manager.close()


def test_create_agent_with_hierarchy_fields(client: TestClient):
    ceo = client.post(
        "/v1/managed-agents",
        json={
            "name": "My Assistant",
            "org_role": "Chief Executive Officer (CEO)",
        },
    )
    assert ceo.status_code == 200
    ceo_id = ceo.json()["id"]

    resp = client.post(
        "/v1/managed-agents",
        json={
            "name": "Project Manager",
            "org_role": "Project Manager",
            "manager_agent_id": ceo_id,
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["org_role"] == "Project Manager"
    assert data["manager_agent_id"] == ceo_id


def test_rejects_cyclic_hierarchy_update(client: TestClient):
    ceo = client.post("/v1/managed-agents", json={"name": "CEO"}).json()
    manager_ = client.post(
        "/v1/managed-agents",
        json={"name": "Manager", "manager_agent_id": ceo["id"]},
    ).json()
    worker = client.post(
        "/v1/managed-agents",
        json={"name": "Worker", "manager_agent_id": manager_["id"]},
    ).json()

    resp = client.patch(
        f"/v1/managed-agents/{ceo['id']}",
        json={"manager_agent_id": worker["id"]},
    )
    assert resp.status_code == 400
    assert "cycle" in resp.json()["detail"].lower()
