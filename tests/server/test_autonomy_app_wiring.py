from __future__ import annotations

from unittest.mock import MagicMock

from openjarvis.core.config import load_config
from openjarvis.core.events import EventBus
from openjarvis.server.app import create_app


def test_app_wires_rollback_store(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENJARVIS_CONFIG", str(tmp_path / "none.toml"))
    cfg = load_config()
    cfg.autonomy.db_path = str(tmp_path / "auto.db")
    app = create_app(MagicMock(), "test-model", bus=EventBus(), config=cfg)
    store = getattr(app.state, "rollback_store", None)
    assert store is not None
    a = store.record(action_type="file_write", summary="x")
    assert store.get(a.id) is not None
    store.close()
