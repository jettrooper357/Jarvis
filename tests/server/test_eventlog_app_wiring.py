from __future__ import annotations

from unittest.mock import MagicMock

from openjarvis.core.config import load_config
from openjarvis.core.events import EventBus, EventType
from openjarvis.server.app import create_app


def test_app_wires_event_log_store(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENJARVIS_CONFIG", str(tmp_path / "none.toml"))
    cfg = load_config()
    cfg.eventlog.db_path = str(tmp_path / "eventlog.db")
    bus = EventBus()
    app = create_app(MagicMock(), "test-model", bus=bus, config=cfg)
    store = getattr(app.state, "event_log_store", None)
    assert store is not None
    bus.publish(EventType.TASK_CREATED, {"task_id": "wired"})
    assert store.query(task_id="wired")
    store.close()
