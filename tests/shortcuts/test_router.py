"""Tests for the /v1/shortcuts REST router."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("pydantic")

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from openjarvis.server.shortcuts_router import create_shortcuts_router  # noqa: E402
from openjarvis.shortcuts.registry import ShortcutRegistry  # noqa: E402


@pytest.fixture()
def client(tmp_path: Path):
    db = tmp_path / "shortcuts.db"
    registry = ShortcutRegistry(db_path=db)
    app = FastAPI()
    app.include_router(create_shortcuts_router(registry=registry))
    return TestClient(app), registry


def _payload(**overrides):
    base = {
        "name": "Test rule",
        "priority": 100,
        "patterns": [{"kind": "phrase", "value": "what's the news"}],
        "target_kind": "tool",
        "target_id": "get_news",
        "arg_template": {},
        "on_failure": "fallback_to_chief",
    }
    base.update(overrides)
    return base


def test_list_starts_empty(client):
    c, _ = client
    resp = c.get("/v1/shortcuts")
    assert resp.status_code == 200
    assert resp.json() == {"rules": []}


def test_create_then_get(client):
    c, _ = client
    resp = c.post("/v1/shortcuts", json=_payload(name="News"))
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "News"
    assert body["id"]
    rule_id = body["id"]

    resp = c.get(f"/v1/shortcuts/{rule_id}")
    assert resp.status_code == 200
    assert resp.json()["name"] == "News"


def test_update_preserves_created_at(client):
    c, _ = client
    created = c.post("/v1/shortcuts", json=_payload(name="A")).json()
    rule_id = created["id"]

    resp = c.put(
        f"/v1/shortcuts/{rule_id}",
        json=_payload(name="B", priority=200),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "B"
    assert body["priority"] == 200
    assert body["created_at"] == created["created_at"]


def test_update_unknown_returns_404(client):
    c, _ = client
    resp = c.put("/v1/shortcuts/nope", json=_payload())
    assert resp.status_code == 404


def test_delete(client):
    c, _ = client
    rule_id = c.post("/v1/shortcuts", json=_payload()).json()["id"]
    resp = c.delete(f"/v1/shortcuts/{rule_id}")
    assert resp.status_code == 200
    assert c.get(f"/v1/shortcuts/{rule_id}").status_code == 404


def test_targets_endpoint(client):
    c, _ = client
    resp = c.get("/v1/shortcuts/targets")
    assert resp.status_code == 200
    body = resp.json()
    assert "tool" in body and isinstance(body["tool"], list)
    assert "skill" in body
    assert "datasource" in body
    assert "preset" in body


def test_test_endpoint_no_match(client):
    c, _ = client
    resp = c.post("/v1/shortcuts/test", json={"message": "nothing matches this"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["matched"] is False
    assert body["handled"] is False


def test_test_endpoint_match_with_passthrough(client):
    c, _ = client
    c.post(
        "/v1/shortcuts",
        json=_payload(
            name="Echo",
            patterns=[{"kind": "phrase", "value": "say hello"}],
            target_id="get_news",  # any real tool will do
            post_prompt="",  # empty = passthrough; no engine call needed
        ),
    )
    resp = c.post("/v1/shortcuts/test", json={"message": "please say hello"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["matched"] is True
    # Tool may fail without RSS config; handled/fallback or error are both OK.
    assert body["rule_name"] == "Echo"
