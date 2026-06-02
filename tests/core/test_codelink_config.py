from __future__ import annotations

from openjarvis.core.config import CodeLinkConfig, JarvisConfig


def test_codelink_config_defaults():
    cfg = CodeLinkConfig()
    assert cfg.enabled is True
    assert cfg.db_path.endswith("codelink.db")
    assert cfg.watch_enabled is False


def test_jarvis_config_has_codelink():
    cfg = JarvisConfig()
    assert isinstance(cfg.codelink, CodeLinkConfig)
    assert cfg.codelink.enabled is True
