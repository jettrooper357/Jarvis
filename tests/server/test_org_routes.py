from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from openjarvis.agents.manager import AgentManager
from openjarvis.server.org_routes import org_router


def _client(manager=None):
    app = FastAPI()
    app.include_router(org_router)
    if manager is not None:
        app.state.agent_manager = manager
    return TestClient(app)


def test_bootstrap_then_tree(tmp_path):
    mgr = AgentManager(db_path=str(tmp_path / "agents.db"))
    client = _client(mgr)
    r = client.post("/v1/org/bootstrap")
    assert r.status_code == 200
    body = r.json()
    assert body["chief_id"]
    assert len(body["created"]) > 0

    r = client.get("/v1/org")
    assert r.status_code == 200
    tree = r.json()["org"]
    assert tree["org_role"] == "chief_orchestrator"
    assert len(tree["reports"]) == 5


def test_bootstrap_503_without_manager():
    client = _client(None)
    assert client.post("/v1/org/bootstrap").status_code == 503


def test_tree_null_without_manager():
    client = _client(None)
    assert client.get("/v1/org").json() == {"org": None}


def test_org_routes_are_mounted():
    from openjarvis.server.api_routes import include_all_routes

    app = FastAPI()
    include_all_routes(app)
    paths = {route.path for route in app.routes}
    assert "/v1/org" in paths
    assert "/v1/org/bootstrap" in paths
