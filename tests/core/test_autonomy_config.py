from __future__ import annotations

from openjarvis.core.config import AutonomyConfig, JarvisConfig


def test_autonomy_config_defaults():
    cfg = AutonomyConfig()
    assert cfg.enabled is True
    assert cfg.db_path.endswith("autonomy.db")


def test_jarvis_config_has_autonomy():
    cfg = JarvisConfig()
    assert isinstance(cfg.autonomy, AutonomyConfig)
    assert cfg.autonomy.enabled is True
