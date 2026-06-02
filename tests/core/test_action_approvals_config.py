from __future__ import annotations

from openjarvis.core.config import ActionApprovalsConfig, JarvisConfig


def test_action_approvals_config_defaults():
    cfg = ActionApprovalsConfig()
    assert cfg.enabled is True
    assert cfg.db_path.endswith("action_approvals.db")


def test_jarvis_config_has_action_approvals():
    cfg = JarvisConfig()
    assert isinstance(cfg.action_approvals, ActionApprovalsConfig)
    assert cfg.action_approvals.enabled is True
