from __future__ import annotations

from unittest.mock import MagicMock

from openjarvis.core.config import load_config
from openjarvis.core.events import EventBus
from openjarvis.server.app import create_app


def test_app_wires_life_store(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENJARVIS_CONFIG", str(tmp_path / "none.toml"))
    cfg = load_config()
    cfg.lifemanager.db_path = str(tmp_path / "life.db")
    app = create_app(MagicMock(), "test-model", bus=EventBus(), config=cfg)
    store = getattr(app.state, "life_store", None)
    assert store is not None
    d = store.add_domain(name="Health")
    assert store.get_domain(d.id) is not None
    store.close()
