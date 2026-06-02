from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from openjarvis.approvals_center.store import ActionApprovalStore
from openjarvis.server.action_approvals_routes import action_approvals_router


def _client(store):
    app = FastAPI()
    app.include_router(action_approvals_router)
    app.state.action_approval_store = store
    return TestClient(app)


def test_create_list_get(tmp_path):
    store = ActionApprovalStore(db_path=str(tmp_path / "aa.db"))
    client = _client(store)
    resp = client.post(
        "/v1/action-approvals",
        json={"action_type": "email", "summary": "Send reply", "payload": {"to": "x"}},
    )
    assert resp.status_code == 200
    aid = resp.json()["id"]
    assert resp.json()["state"] == "pending"

    resp = client.get("/v1/action-approvals")
    assert len(resp.json()["approvals"]) == 1
    resp = client.get("/v1/action-approvals", params={"action_type": "email"})
    assert len(resp.json()["approvals"]) == 1

    resp = client.get(f"/v1/action-approvals/{aid}")
    assert resp.status_code == 200
    assert resp.json()["summary"] == "Send reply"
    assert "created_at" in resp.json()

    resp = client.get("/v1/action-approvals/nope")
    assert resp.status_code == 404
    store.close()


def test_resolve_actions(tmp_path):
    store = ActionApprovalStore(db_path=str(tmp_path / "aa.db"))
    client = _client(store)
    aid = client.post(
        "/v1/action-approvals",
        json={"action_type": "deploy", "summary": "ship"},
    ).json()["id"]

    resp = client.post(
        f"/v1/action-approvals/{aid}/resolve",
        json={"action": "approve", "resolved_by": "user", "reason": "lgtm"},
    )
    assert resp.status_code == 200
    assert resp.json()["state"] == "approved"

    resp = client.post(
        f"/v1/action-approvals/{aid}/resolve",
        json={"action": "reject"},
    )
    assert resp.status_code == 409

    resp = client.get(f"/v1/action-approvals/{aid}/history")
    assert resp.status_code == 200
    assert [e["to_state"] for e in resp.json()["history"]] == ["pending", "approved"]
    store.close()


def test_unknown_action_422(tmp_path):
    store = ActionApprovalStore(db_path=str(tmp_path / "aa.db"))
    client = _client(store)
    aid = client.post(
        "/v1/action-approvals", json={"action_type": "x", "summary": "y"}
    ).json()["id"]
    resp = client.post(
        f"/v1/action-approvals/{aid}/resolve", json={"action": "frobnicate"}
    )
    assert resp.status_code == 422
    store.close()


def test_missing_store():
    app = FastAPI()
    app.include_router(action_approvals_router)
    client = TestClient(app)
    assert client.get("/v1/action-approvals").json() == {"approvals": []}
    resp = client.post(
        "/v1/action-approvals", json={"action_type": "x", "summary": "y"}
    )
    assert resp.status_code == 503
