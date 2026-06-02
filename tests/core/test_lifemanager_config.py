from __future__ import annotations

from openjarvis.core.config import JarvisConfig, LifeManagerConfig


def test_lifemanager_config_defaults():
    cfg = LifeManagerConfig()
    assert cfg.enabled is True
    assert cfg.db_path.endswith("lifemanager.db")


def test_jarvis_config_has_lifemanager():
    cfg = JarvisConfig()
    assert isinstance(cfg.lifemanager, LifeManagerConfig)
    assert cfg.lifemanager.enabled is True
