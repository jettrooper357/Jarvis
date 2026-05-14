"""Tests for the /v1/connectors API router."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def app():
    try:
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
    except ImportError:
        pytest.skip("fastapi not installed")

    from openjarvis.server.connectors_router import create_connectors_router

    _app = FastAPI()
    router = create_connectors_router()
    _app.include_router(router)
    return TestClient(_app)


def test_list_connectors(app):
    """GET /v1/connectors returns a list that includes the obsidian connector."""
    resp = app.get("/v1/connectors")
    assert resp.status_code == 200
    data = resp.json()
    assert "connectors" in data
    ids = [c["connector_id"] for c in data["connectors"]]
    assert "obsidian" in ids


def test_connector_detail(app):
    """GET /v1/connectors/obsidian returns the expected fields."""
    resp = app.get("/v1/connectors/obsidian")
    assert resp.status_code == 200
    data = resp.json()
    assert data["connector_id"] == "obsidian"
    assert "display_name" in data
    assert "auth_type" in data
    assert "connected" in data
    assert "mcp_tools" in data


def test_connector_not_found(app):
    """GET /v1/connectors/nonexistent returns 404."""
    resp = app.get("/v1/connectors/nonexistent")
    assert resp.status_code == 404


def test_connect_obsidian(app, tmp_path):
    """POST /v1/connectors/obsidian/connect with a valid path marks it connected."""
    # Create a minimal vault directory so is_connected() returns True.
    vault = tmp_path / "vault"
    vault.mkdir()

    resp = app.post("/v1/connectors/obsidian/connect", json={"path": str(vault)})
    assert resp.status_code == 200
    data = resp.json()
    assert data["connector_id"] == "obsidian"
    assert data["connected"] is True


def test_disconnect(app):
    """POST /v1/connectors/obsidian/disconnect returns 200 with connected=False."""
    resp = app.post("/v1/connectors/obsidian/disconnect")
    assert resp.status_code == 200
    data = resp.json()
    assert data["connector_id"] == "obsidian"
    assert data["connected"] is False


def test_sync_status(app):
    """GET /v1/connectors/obsidian/sync returns a response with a state field."""
    resp = app.get("/v1/connectors/obsidian/sync")
    assert resp.status_code == 200
    data = resp.json()
    assert "state" in data
    assert data["connector_id"] == "obsidian"


def test_trigger_sync(app, tmp_path: Path) -> None:
    """POST /v1/connectors/obsidian/sync triggers an incremental sync."""
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "note.md").write_text("# Test note\n\nContent here.")
    app.post("/v1/connectors/obsidian/connect", json={"path": str(vault)})
    resp = app.post("/v1/connectors/obsidian/sync")
    assert resp.status_code == 200
    data = resp.json()
    assert data["connector_id"] == "obsidian"
    assert data["status"] in {"started", "already_syncing"}


def test_save_google_oauth_client(app, monkeypatch) -> None:
    """POST /v1/connectors/oauth-clients/google accepts wrapped client JSON."""
    saved: dict[str, str] = {}

    def _fake_save_client_credentials(provider, client_id: str, client_secret: str) -> None:
        saved["provider"] = provider.name
        saved["client_id"] = client_id
        saved["client_secret"] = client_secret

    monkeypatch.setattr(
        "openjarvis.connectors.oauth.save_client_credentials",
        _fake_save_client_credentials,
    )

    resp = app.post(
        "/v1/connectors/oauth-clients/google",
        json={
            "installed": {
                "client_id": "abc123.apps.googleusercontent.com",
                "client_secret": "super-secret",
            }
        },
    )

    assert resp.status_code == 200
    assert saved == {
        "provider": "google",
        "client_id": "abc123.apps.googleusercontent.com",
        "client_secret": "super-secret",
    }
    data = resp.json()
    assert data["provider"] == "google"
    assert "abc123.apps" in data["client_id_preview"]


def test_google_oauth_callback_clears_all_provider_instances(app, monkeypatch) -> None:
    """A successful Google callback should invalidate all cached Google connectors."""
    from openjarvis.connectors.oauth import OAUTH_PROVIDERS
    from openjarvis.server.connectors_router import _instances

    provider = OAUTH_PROVIDERS["google"]
    saved_paths: list[str] = []

    monkeypatch.setattr(
        "openjarvis.connectors.oauth.get_provider_for_connector",
        lambda connector_id: provider if connector_id in provider.connector_ids else None,
    )
    monkeypatch.setattr(
        "openjarvis.connectors.oauth.get_client_credentials",
        lambda _provider: ("client-id", "client-secret"),
    )
    monkeypatch.setattr(
        "openjarvis.connectors.oauth._exchange_token",
        lambda *_args, **_kwargs: {
            "access_token": "access-token",
            "refresh_token": "refresh-token",
            "token_type": "Bearer",
            "expires_in": 3600,
        },
    )
    monkeypatch.setattr(
        "openjarvis.connectors.oauth.save_tokens",
        lambda path, payload: saved_paths.append(path),
    )

    try:
        for connector_id in provider.connector_ids:
            _instances[connector_id] = object()

        resp = app.get("/v1/connectors/gdrive/oauth/callback?code=test-code")

        assert resp.status_code == 200
        assert all(connector_id not in _instances for connector_id in provider.connector_ids)
        assert len(saved_paths) == len(provider.credential_files)
    finally:
        for connector_id in provider.connector_ids:
            _instances.pop(connector_id, None)
