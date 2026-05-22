"""Phase 2A/2B — preview / versions / revert route tests."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from openjarvis.agents.manager import AgentManager

try:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    HAS_FASTAPI = True
except ImportError:  # pragma: no cover
    HAS_FASTAPI = False


@pytest.fixture
def manager():
    with tempfile.TemporaryDirectory() as tmpdir:
        mgr = AgentManager(db_path=str(Path(tmpdir) / "agents.db"))
        yield mgr
        mgr.close()


@pytest.fixture
def client(manager):
    if not HAS_FASTAPI:
        pytest.skip("fastapi not installed")
    from openjarvis.server.agent_manager_routes import create_agent_manager_router

    app = FastAPI()
    routers = create_agent_manager_router(manager)
    agents_router, templates_router, global_router, tools_router, *_ = routers
    app.include_router(agents_router)
    app.include_router(templates_router)
    app.include_router(global_router)
    app.include_router(tools_router)
    return TestClient(app)


# ── /preview ──────────────────────────────────────────────────────────


def test_preview_returns_axes_without_persisting(client, manager):
    create = client.post(
        "/v1/managed-agents",
        json={
            "name": "previewer",
            "config": {"skills": ["a"], "knowledge_enabled": False},
        },
    )
    agent_id = create.json()["id"]

    resp = client.post(
        f"/v1/managed-agents/{agent_id}/preview",
        json={"config_overrides": {"skills": ["a", "b"]}},
    )
    assert resp.status_code == 200
    body = resp.json()
    # Override reflected in preview output.
    assert "b" in body["configured_skills"]
    # Axis keys present.
    for key in (
        "inherited_skills",
        "inherited_tools",
        "blocked_skills",
        "blocked_tools",
        "requires_approval_skills",
        "requires_approval_tools",
    ):
        assert key in body
    # Nothing persisted — fetching the agent shows the original skills.
    after = client.get(f"/v1/managed-agents/{agent_id}").json()
    assert after["configured_skills"] == ["a"]


def test_preview_with_no_overrides_returns_current(client, manager):
    create = client.post(
        "/v1/managed-agents",
        json={"name": "p2", "config": {"skills": ["x"], "knowledge_enabled": False}},
    )
    agent_id = create.json()["id"]
    resp = client.post(f"/v1/managed-agents/{agent_id}/preview", json={})
    assert resp.status_code == 200
    assert resp.json()["configured_skills"] == ["x"]


def test_preview_unknown_agent_returns_404(client):
    resp = client.post("/v1/managed-agents/nope/preview", json={})
    assert resp.status_code == 404


# ── /versions and /revert ─────────────────────────────────────────────


def test_versions_empty_then_populated(client, manager):
    create = client.post(
        "/v1/managed-agents",
        json={"name": "versioned", "config": {"v": 1, "knowledge_enabled": False}},
    )
    agent_id = create.json()["id"]
    listing = client.get(f"/v1/managed-agents/{agent_id}/versions").json()
    assert listing["versions"] == []

    client.patch(
        f"/v1/managed-agents/{agent_id}",
        json={"config": {"v": 2, "knowledge_enabled": False}},
    )
    listing = client.get(f"/v1/managed-agents/{agent_id}/versions").json()
    assert len(listing["versions"]) == 1
    assert listing["versions"][0]["version_number"] == 1
    assert listing["versions"][0]["snapshot"]["v"] == 2


def test_revert_appends_new_version_and_restores_snapshot(client, manager):
    create = client.post(
        "/v1/managed-agents",
        json={"name": "rewinder", "config": {"v": 1, "knowledge_enabled": False}},
    )
    agent_id = create.json()["id"]
    client.patch(
        f"/v1/managed-agents/{agent_id}",
        json={"config": {"v": 2, "knowledge_enabled": False}},
    )
    client.patch(
        f"/v1/managed-agents/{agent_id}",
        json={"config": {"v": 3, "knowledge_enabled": False}},
    )

    listing = client.get(f"/v1/managed-agents/{agent_id}/versions").json()
    v1 = next(v for v in listing["versions"] if v["version_number"] == 1)

    revert = client.post(
        f"/v1/managed-agents/{agent_id}/revert",
        json={"version_id": v1["id"], "updated_by": "tester"},
    )
    assert revert.status_code == 200
    assert revert.json()["config"]["v"] == 2

    after = client.get(f"/v1/managed-agents/{agent_id}/versions").json()
    # Append-only: three pre-revert + one revert row = 4? Actually the
    # version-on-update fires for each of the two PATCH calls (1, 2) and
    # then again for the revert (3). The very first create_agent does
    # not produce a version row (initial snapshot is implicit).
    numbers = [v["version_number"] for v in after["versions"]]
    assert numbers == sorted(numbers, reverse=True)
    assert after["versions"][0]["summary"].startswith("Revert to version")


def test_revert_unknown_version_returns_404(client, manager):
    create = client.post("/v1/managed-agents", json={"name": "x"})
    agent_id = create.json()["id"]
    resp = client.post(
        f"/v1/managed-agents/{agent_id}/revert",
        json={"version_id": "deadbeef"},
    )
    assert resp.status_code == 404


def test_versions_for_unknown_agent_returns_404(client):
    resp = client.get("/v1/managed-agents/nope/versions")
    assert resp.status_code == 404


def test_inheritance_populated_via_get_agent(client, manager):
    """Manager's skills appear in subordinate's inherited_skills."""
    mgr_resp = client.post(
        "/v1/managed-agents",
        json={
            "name": "boss",
            "config": {"skills": ["budget"], "knowledge_enabled": False},
        },
    )
    mgr_id = mgr_resp.json()["id"]
    sub_resp = client.post(
        "/v1/managed-agents",
        json={
            "name": "worker",
            "manager_agent_id": mgr_id,
            "config": {"skills": ["ui"], "knowledge_enabled": False},
        },
    )
    sub_id = sub_resp.json()["id"]
    sub = client.get(f"/v1/managed-agents/{sub_id}").json()
    assert sub["inherited_skills"] == ["budget"]
    assert sub["configured_skills"] == ["ui"]
