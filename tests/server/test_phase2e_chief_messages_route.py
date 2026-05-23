"""Phase 2E commit 1 — /v1/chief/* route tests.

Covers:
- GET /v1/chief returns 404 with no chief, agent record with one set.
- POST /v1/chief/designate flips the designation atomically.
- POST /v1/chief/messages returns 412 when the flag is OFF.
- POST /v1/chief/messages returns 412 with a CTA payload when no chief.
- POST /v1/chief/messages dispatches to the Chief when both conditions met.
- The existing /v1/managed-agents routes still behave (regression).
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from openjarvis.agents.manager import AgentManager
from openjarvis.core.config import ChiefIngressConfig


try:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    HAS_FASTAPI = True
except ImportError:  # pragma: no cover
    HAS_FASTAPI = False


def _make_app(manager, *, chief_enabled: bool):
    from openjarvis.server.agent_manager_routes import create_agent_manager_router

    app = FastAPI()
    # The chief route reads ``request.app.state.config.chief_ingress.enabled``.
    app.state.config = SimpleNamespace(
        chief_ingress=ChiefIngressConfig(enabled=chief_enabled)
    )
    routers = create_agent_manager_router(manager)
    for r in routers:
        app.include_router(r)
    return app


@pytest.fixture
def manager_and_client_factory():
    if not HAS_FASTAPI:
        pytest.skip("fastapi not installed")

    created = []

    def _factory(*, chief_enabled: bool):
        tmp = tempfile.TemporaryDirectory()
        mgr = AgentManager(db_path=str(Path(tmp.name) / "agents.db"))
        app = _make_app(mgr, chief_enabled=chief_enabled)
        client = TestClient(app)
        created.append((tmp, mgr))
        return mgr, client

    yield _factory

    for tmp, mgr in created:
        mgr.close()
        tmp.cleanup()


# ── GET /v1/chief ──────────────────────────────────────────────────────


def test_get_chief_404_when_none(manager_and_client_factory):
    _mgr, client = manager_and_client_factory(chief_enabled=False)
    r = client.get("/v1/chief")
    assert r.status_code == 404


def test_get_chief_returns_designated_record(manager_and_client_factory):
    mgr, client = manager_and_client_factory(chief_enabled=False)
    a = mgr.create_agent("first")
    mgr.set_chief_agent(a["id"])
    r = client.get("/v1/chief")
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == a["id"]
    assert body["is_chief"] is True


# ── POST /v1/chief/designate ──────────────────────────────────────────


def test_designate_chief_flips_designation(manager_and_client_factory):
    mgr, client = manager_and_client_factory(chief_enabled=False)
    a = mgr.create_agent("a")
    b = mgr.create_agent("b")
    r1 = client.post("/v1/chief/designate", json={"agent_id": a["id"]})
    assert r1.status_code == 200
    assert r1.json()["id"] == a["id"]
    r2 = client.post("/v1/chief/designate", json={"agent_id": b["id"]})
    assert r2.status_code == 200
    assert r2.json()["id"] == b["id"]
    # a is no longer chief
    assert mgr.get_agent(a["id"])["is_chief"] is False


def test_designate_unknown_agent_returns_404(manager_and_client_factory):
    _mgr, client = manager_and_client_factory(chief_enabled=False)
    r = client.post("/v1/chief/designate", json={"agent_id": "nope"})
    assert r.status_code == 404


# ── POST /v1/chief/messages ───────────────────────────────────────────


def test_messages_412_when_flag_off(manager_and_client_factory):
    mgr, client = manager_and_client_factory(chief_enabled=False)
    a = mgr.create_agent("c")
    mgr.set_chief_agent(a["id"])
    r = client.post("/v1/chief/messages", json={"content": "hi"})
    assert r.status_code == 412
    detail = r.json()["detail"]
    assert detail["error"] == "chief_ingress_disabled"


def test_messages_412_when_no_chief_designated(manager_and_client_factory):
    mgr, client = manager_and_client_factory(chief_enabled=True)
    mgr.create_agent("worker-1")
    mgr.create_agent("worker-2")
    r = client.post("/v1/chief/messages", json={"content": "hi"})
    assert r.status_code == 412
    detail = r.json()["detail"]
    assert detail["error"] == "no_chief_designated"
    assert detail["action"] == "designate_chief"
    # CTA: lists the available agents the user can promote.
    names = {a["name"] for a in detail["available_agents"]}
    assert names == {"worker-1", "worker-2"}


def test_messages_dispatches_when_flag_on_and_chief_set(manager_and_client_factory):
    """Queued mode: the message must be persisted via send_message under
    the Chief's agent id (so list_messages on the Chief returns it)."""
    mgr, client = manager_and_client_factory(chief_enabled=True)
    a = mgr.create_agent("the chief")
    mgr.set_chief_agent(a["id"])
    r = client.post(
        "/v1/chief/messages",
        json={"content": "hello chief", "mode": "queued"},
    )
    assert r.status_code == 200
    body = r.json()
    # Returned record is the persisted user message.
    assert body["content"] == "hello chief"
    # Verify persistence under the chief's agent id (cross-route confirmation).
    msgs = client.get(f"/v1/managed-agents/{a['id']}/messages").json()["messages"]
    assert any(m["content"] == "hello chief" for m in msgs)


# ── Regression: /v1/managed-agents still works ────────────────────────


def test_existing_agent_routes_still_work(manager_and_client_factory):
    mgr, client = manager_and_client_factory(chief_enabled=True)
    a = mgr.create_agent("co-existing")
    r = client.get(f"/v1/managed-agents/{a['id']}")
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == a["id"]
    # is_chief is now part of the standard enriched record shape.
    assert body["is_chief"] is False


def test_chief_path_does_not_collide_with_agent_id_param(manager_and_client_factory):
    """An agent literally named 'chief' (with a normal hex id) must
    still be reachable under /v1/managed-agents/{id} without the chief
    route swallowing the request."""
    mgr, client = manager_and_client_factory(chief_enabled=True)
    a = mgr.create_agent("chief")  # name 'chief' but id is a hex
    r = client.get(f"/v1/managed-agents/{a['id']}")
    assert r.status_code == 200
    # And the chief router is reachable independently.
    r2 = client.get("/v1/chief")
    # No designated chief yet → 404, but the route is being hit.
    assert r2.status_code == 404


# ── GET /v1/chief/status (health) ──────────────────────────────────────


def test_status_reports_disabled_and_no_chief(manager_and_client_factory):
    _mgr, client = manager_and_client_factory(chief_enabled=False)
    r = client.get("/v1/chief/status")
    assert r.status_code == 200
    body = r.json()
    assert body == {"enabled": False, "chief_id": None, "chief_name": None}


def test_status_reports_enabled_and_chief_set(manager_and_client_factory):
    mgr, client = manager_and_client_factory(chief_enabled=True)
    a = mgr.create_agent("boss")
    mgr.set_chief_agent(a["id"])
    r = client.get("/v1/chief/status")
    body = r.json()
    assert body["enabled"] is True
    assert body["chief_id"] == a["id"]
    assert body["chief_name"] == "boss"


def test_status_reports_enabled_but_no_chief(manager_and_client_factory):
    _mgr, client = manager_and_client_factory(chief_enabled=True)
    r = client.get("/v1/chief/status")
    body = r.json()
    assert body == {"enabled": True, "chief_id": None, "chief_name": None}


# ── Commit 3 — flag default is now live ───────────────────────────────


def test_chief_ingress_default_is_enabled():
    """Phase 2E commit 3 flipped the default to True ("make it live").

    Locks the default so a future edit can't silently disable the
    feature without updating this test (and the CIN).
    """
    assert ChiefIngressConfig().enabled is True
