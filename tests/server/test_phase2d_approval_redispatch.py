"""Phase 2D enforcement (stage 2) — Option B auto-resume on grant.

Covers the ``/v1/approvals/{id}/grant`` re-dispatch: when
``approval_gating.enabled`` is set, granting a pending approval re-runs
the blocked agent's most recent user message so the gate, now finding
the grant, lets the previously-blocked tool through. With the flag off
the grant is recorded but no re-run fires (Option A behaviour).

See ``docs/CHANGE_IMPACT_NOTICES/approval-enforcement-at-tool-dispatch.md``.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from openjarvis.agents.approvals import ApprovalStore
from openjarvis.agents.manager import AgentManager
from openjarvis.core.config import ApprovalGatingConfig

try:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    HAS_FASTAPI = True
except ImportError:
    HAS_FASTAPI = False

pytestmark = pytest.mark.skipif(not HAS_FASTAPI, reason="fastapi not installed")


class _ImmediateThread:
    """Stand-in for ``threading.Thread`` that runs the target inline."""

    def __init__(self, target=None, daemon=None):
        self._target = target

    def start(self):
        if self._target:
            self._target()


@pytest.fixture
def env():
    with tempfile.TemporaryDirectory() as tmpdir:
        db = str(Path(tmpdir) / "agents.db")
        manager = AgentManager(db_path=db)
        store = ApprovalStore(db)
        yield manager, store
        store.close()
        manager.close()


def _client(manager, store, *, enabled: bool) -> TestClient:
    from openjarvis.server.agent_manager_routes import create_agent_manager_router

    app = FastAPI()
    app.state.engine = MagicMock()
    app.state.model = "test-model"
    app.state.trace_store = None
    app.state.approval_store = store
    app.state.config = SimpleNamespace(
        approval_gating=ApprovalGatingConfig(enabled=enabled)
    )
    for router in create_agent_manager_router(manager, approval_store=store):
        app.include_router(router)
    return TestClient(app)


def _pending(store, agent_id: str):
    return store.request(
        agent_id=agent_id,
        capability="delete_files",
        args={"path": "/tmp/x"},
        summary="needs a human",
    )


def test_grant_with_flag_on_redispatches_agent(env, monkeypatch):
    manager, store = env
    agent = manager.create_agent(name="Gated", agent_type="simple")
    manager.send_message(agent["id"], "delete the temp files", mode="queued")
    req = _pending(store, agent["id"])

    calls: list[tuple[str, str]] = []

    def _fake_run(self, agent_id, user_content, **kwargs):
        calls.append((agent_id, user_content))
        return "done"

    monkeypatch.setattr(
        "openjarvis.server.managed_agent_runtime.ManagedAgentRuntime.run",
        _fake_run,
    )
    monkeypatch.setattr("threading.Thread", _ImmediateThread)

    client = _client(manager, store, enabled=True)
    resp = client.post(
        f"/v1/approvals/{req.id}/grant",
        json={"resolved_by": "human-admin"},
    )

    assert resp.status_code == 200
    assert resp.json()["state"] == "granted"
    assert calls == [(agent["id"], "delete the temp files")]


def test_grant_with_flag_off_does_not_redispatch(env, monkeypatch):
    manager, store = env
    agent = manager.create_agent(name="Gated", agent_type="simple")
    manager.send_message(agent["id"], "delete the temp files", mode="queued")
    req = _pending(store, agent["id"])

    calls: list = []
    monkeypatch.setattr(
        "openjarvis.server.managed_agent_runtime.ManagedAgentRuntime.run",
        lambda self, *a, **k: calls.append(a),
    )
    monkeypatch.setattr("threading.Thread", _ImmediateThread)

    client = _client(manager, store, enabled=False)
    resp = client.post(
        f"/v1/approvals/{req.id}/grant",
        json={"resolved_by": "human-admin"},
    )

    assert resp.status_code == 200
    assert resp.json()["state"] == "granted"
    assert calls == []


def test_grant_redispatch_failure_does_not_break_grant(env, monkeypatch):
    """A re-dispatch error is swallowed — the grant still succeeds."""
    manager, store = env
    agent = manager.create_agent(name="Gated", agent_type="simple")
    manager.send_message(agent["id"], "delete the temp files", mode="queued")
    req = _pending(store, agent["id"])

    def _boom(self, *a, **k):
        raise RuntimeError("engine exploded")

    monkeypatch.setattr(
        "openjarvis.server.managed_agent_runtime.ManagedAgentRuntime.run",
        _boom,
    )
    monkeypatch.setattr("threading.Thread", _ImmediateThread)

    client = _client(manager, store, enabled=True)
    resp = client.post(
        f"/v1/approvals/{req.id}/grant",
        json={"resolved_by": "human-admin"},
    )

    assert resp.status_code == 200
    assert resp.json()["state"] == "granted"


def test_grant_redispatch_skipped_when_no_user_message(env, monkeypatch):
    """No prior user message → nothing to re-dispatch, grant still ok."""
    manager, store = env
    agent = manager.create_agent(name="Gated", agent_type="simple")
    req = _pending(store, agent["id"])

    calls: list = []
    monkeypatch.setattr(
        "openjarvis.server.managed_agent_runtime.ManagedAgentRuntime.run",
        lambda self, *a, **k: calls.append(a),
    )
    monkeypatch.setattr("threading.Thread", _ImmediateThread)

    client = _client(manager, store, enabled=True)
    resp = client.post(
        f"/v1/approvals/{req.id}/grant",
        json={"resolved_by": "human-admin"},
    )

    assert resp.status_code == 200
    assert calls == []
