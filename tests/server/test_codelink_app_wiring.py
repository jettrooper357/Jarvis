from __future__ import annotations

from unittest.mock import MagicMock

from openjarvis.core.config import load_config
from openjarvis.core.events import EventBus
from openjarvis.server.app import create_app


def test_app_wires_codelink_store(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENJARVIS_CONFIG", str(tmp_path / "none.toml"))
    cfg = load_config()
    cfg.codelink.db_path = str(tmp_path / "cl.db")
    cfg.codelink.watch_enabled = False
    app = create_app(MagicMock(), "test-model", bus=EventBus(), config=cfg)
    store = getattr(app.state, "codelink_store", None)
    assert store is not None
    fe = store.record_file_event(path="x.py", change_type="created")
    assert store.file_events(path="x.py")[0].id == fe.id
    store.close()
