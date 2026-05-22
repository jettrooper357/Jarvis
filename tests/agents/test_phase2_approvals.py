"""Phase 2D — ApprovalStore unit + routes integration tests."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from openjarvis.agents.approvals import ApprovalError, ApprovalStore
from openjarvis.agents.manager import AgentManager
from openjarvis.core.events import EventBus, EventType


# ── Unit: ApprovalStore ───────────────────────────────────────────────


def _store(tmp_path, bus=None):
    return ApprovalStore(str(tmp_path / "approvals.db"), event_bus=bus)


def test_request_creates_pending_with_payload(tmp_path):
    store = _store(tmp_path)
    req = store.request(
        agent_id="agt-1",
        capability="wire_money",
        args={"amount": 1000, "currency": "USD"},
        task_id="task-x",
        summary="High-value transfer",
        requested_by="agt-1",
    )
    assert req.state == "pending"
    assert req.capability == "wire_money"
    assert req.args == {"amount": 1000, "currency": "USD"}
    fetched = store.get(req.id)
    assert fetched is not None
    assert fetched.state == "pending"
    store.close()


def test_request_emits_approval_requested(tmp_path):
    bus = EventBus(record_history=True)
    store = _store(tmp_path, bus=bus)
    store.request(
        agent_id="agt-1", capability="delete_files", args={"path": "/tmp/x"}
    )
    types = [e.event_type for e in bus.history]
    assert EventType.APPROVAL_REQUESTED in types
    store.close()


def test_grant_transitions_and_emits_resolved(tmp_path):
    bus = EventBus(record_history=True)
    store = _store(tmp_path, bus=bus)
    req = store.request(agent_id="agt-1", capability="x")
    bus._history.clear()  # type: ignore[attr-defined]
    granted = store.grant(req.id, resolved_by="user-alice", reason="ok")
    assert granted.state == "granted"
    assert granted.decision == "granted"
    assert granted.resolved_by == "user-alice"
    assert granted.reason == "ok"
    types = [e.event_type for e in bus.history]
    assert EventType.APPROVAL_RESOLVED in types
    store.close()


def test_deny_transitions_and_emits_resolved(tmp_path):
    bus = EventBus(record_history=True)
    store = _store(tmp_path, bus=bus)
    req = store.request(agent_id="agt-1", capability="x")
    denied = store.deny(req.id, resolved_by="user-bob", reason="no")
    assert denied.state == "denied"
    assert denied.decision == "denied"
    types = [e.event_type for e in bus.history]
    assert EventType.APPROVAL_RESOLVED in types
    store.close()


def test_resolution_is_immutable(tmp_path):
    store = _store(tmp_path)
    req = store.request(agent_id="agt-1", capability="x")
    store.grant(req.id)
    with pytest.raises(ApprovalError):
        store.grant(req.id)  # second grant
    with pytest.raises(ApprovalError):
        store.deny(req.id)  # post-grant deny
    store.close()


def test_unknown_id_raises(tmp_path):
    store = _store(tmp_path)
    with pytest.raises(ApprovalError):
        store.grant("nonexistent")
    with pytest.raises(ApprovalError):
        store.deny("nonexistent")
    store.close()


def test_list_filters_by_agent_and_state(tmp_path):
    store = _store(tmp_path)
    r1 = store.request(agent_id="a1", capability="x")
    r2 = store.request(agent_id="a1", capability="y")
    store.request(agent_id="a2", capability="z")
    store.grant(r1.id)
    store.deny(r2.id)
    assert {r.id for r in store.list(agent_id="a1")} == {r1.id, r2.id}
    assert [r.id for r in store.list(agent_id="a1", state="granted")] == [r1.id]
    assert [r.id for r in store.list(state="denied")] == [r2.id]
    store.close()


def test_publish_failure_does_not_break_resolution(tmp_path):
    """A bad subscriber must not break the lifecycle."""
    bus = EventBus()

    def angry(_event):
        raise RuntimeError("boom")
    bus.subscribe(EventType.APPROVAL_RESOLVED, angry)
    store = _store(tmp_path, bus=bus)
    req = store.request(agent_id="x", capability="y")
    granted = store.grant(req.id)
    assert granted.state == "granted"
    store.close()


# ── Routes integration ────────────────────────────────────────────────


try:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    HAS_FASTAPI = True
except ImportError:  # pragma: no cover
    HAS_FASTAPI = False


@pytest.fixture
def routes_client(tmp_path):
    if not HAS_FASTAPI:
        pytest.skip("fastapi not installed")
    from openjarvis.server.agent_manager_routes import create_agent_manager_router

    db_dir = tempfile.TemporaryDirectory()
    mgr = AgentManager(db_path=str(Path(db_dir.name) / "agents.db"))
    store = ApprovalStore(str(Path(db_dir.name) / "approvals.db"))
    app = FastAPI()
    routers = create_agent_manager_router(mgr, approval_store=store)
    for r in routers:
        app.include_router(r)
    yield TestClient(app), store
    mgr.close()
    store.close()
    db_dir.cleanup()


def test_routes_503_when_no_store_supplied(tmp_path):
    if not HAS_FASTAPI:
        pytest.skip("fastapi not installed")
    from openjarvis.server.agent_manager_routes import create_agent_manager_router

    mgr = AgentManager(db_path=str(tmp_path / "agents.db"))
    app = FastAPI()
    routers = create_agent_manager_router(mgr)  # no approval_store
    for r in routers:
        app.include_router(r)
    client = TestClient(app)
    resp = client.get("/v1/approvals")
    assert resp.status_code == 503
    mgr.close()


def test_list_approvals_endpoint(routes_client):
    client, store = routes_client
    store.request(agent_id="a", capability="x", summary="first")
    store.request(agent_id="b", capability="y", summary="second")
    resp = client.get("/v1/approvals")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["approvals"]) == 2


def test_get_grant_deny_flow_via_routes(routes_client):
    client, store = routes_client
    req = store.request(agent_id="a", capability="x")
    # Get
    r = client.get(f"/v1/approvals/{req.id}")
    assert r.status_code == 200
    assert r.json()["state"] == "pending"
    # Grant
    g = client.post(
        f"/v1/approvals/{req.id}/grant",
        json={"resolved_by": "tester", "reason": "ok"},
    )
    assert g.status_code == 200
    assert g.json()["state"] == "granted"
    # Second grant is 409
    g2 = client.post(
        f"/v1/approvals/{req.id}/grant", json={}
    )
    assert g2.status_code == 409
    # Deny after grant also 409
    d = client.post(f"/v1/approvals/{req.id}/deny", json={})
    assert d.status_code == 409


def test_unknown_id_returns_404(routes_client):
    client, _ = routes_client
    r = client.get("/v1/approvals/deadbeef")
    assert r.status_code == 404
