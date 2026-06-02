from __future__ import annotations

from openjarvis.core.config import EventLogConfig, JarvisConfig


def test_eventlog_config_defaults():
    cfg = EventLogConfig()
    assert cfg.enabled is True
    assert cfg.db_path.endswith("eventlog.db")
    assert cfg.denylist == []


def test_jarvis_config_has_eventlog():
    cfg = JarvisConfig()
    assert isinstance(cfg.eventlog, EventLogConfig)
    assert cfg.eventlog.enabled is True
