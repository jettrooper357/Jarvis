from __future__ import annotations

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from openjarvis.server.watchtower_routes import create_watchtower_router  # noqa: E402
from openjarvis.watchtower.service import WatchtowerService  # noqa: E402
from openjarvis.watchtower.store import WatchtowerStore  # noqa: E402
from openjarvis.watchtower.types import Priority, WatchtowerSettings  # noqa: E402


def _client(tmp_path):
    app = FastAPI()
    store = WatchtowerStore(tmp_path / "watchtower.db")
    app.state.watchtower_store = store
    app.state.watchtower_service = WatchtowerService(
        store=store,
        settings=WatchtowerSettings(telegram_enabled=False),
    )
    app.include_router(create_watchtower_router())
    return TestClient(app), store


def test_watchtower_status_and_settings_routes(tmp_path) -> None:
    client, store = _client(tmp_path)

    assert client.get("/v1/watchtower/status").status_code == 200
    response = client.patch(
        "/v1/watchtower/settings",
        json={"telegram_min_priority": "urgent", "loop_interval_seconds": 120},
    )

    assert response.status_code == 200
    assert response.json()["telegram_min_priority"] == "urgent"
    assert response.json()["loop_interval_seconds"] == 120
    store.close()


def test_watchtower_findings_routes(tmp_path) -> None:
    client, store = _client(tmp_path)
    finding = store.upsert_finding(
        finding_type="blocked_agent",
        entity_type="agent",
        entity_id="a1",
        priority=Priority.HIGH,
        reason="blocked",
    )

    listed = client.get("/v1/watchtower/findings")
    assert listed.status_code == 200
    assert listed.json()["findings"][0]["finding_id"] == finding.finding_id

    resolved = client.post(
        f"/v1/watchtower/findings/{finding.finding_id}/resolve", json={}
    )
    assert resolved.status_code == 200
    assert resolved.json()["status"] == "resolved"
    store.close()
