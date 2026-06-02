from __future__ import annotations

from openjarvis.agents.manager import AgentManager


def _mgr(tmp_path):
    return AgentManager(db_path=str(tmp_path / "agents.db"))


def test_template_org_role_used_when_caller_passes_none(tmp_path, monkeypatch):
    mgr = _mgr(tmp_path)
    monkeypatch.setattr(
        mgr,
        "list_templates",
        lambda: [
            {
                "id": "role_tpl",
                "name": "Role Tpl",
                "agent_type": "simple",
                "org_role": "widget_maker",
                "system_prompt_template": "hi {instruction}",
            }
        ],
    )
    agent = mgr.create_from_template("role_tpl", name="W1")
    assert agent["org_role"] == "widget_maker"
    assert "org_role" not in agent["config"]


def test_explicit_org_role_overrides_template(tmp_path, monkeypatch):
    mgr = _mgr(tmp_path)
    monkeypatch.setattr(
        mgr,
        "list_templates",
        lambda: [
            {
                "id": "role_tpl",
                "name": "Role Tpl",
                "agent_type": "simple",
                "org_role": "widget_maker",
            }
        ],
    )
    agent = mgr.create_from_template("role_tpl", name="W1", org_role="override")
    assert agent["org_role"] == "override"


def test_template_without_org_role_defaults_empty(tmp_path, monkeypatch):
    mgr = _mgr(tmp_path)
    monkeypatch.setattr(
        mgr,
        "list_templates",
        lambda: [{"id": "plain", "name": "Plain", "agent_type": "simple"}],
    )
    agent = mgr.create_from_template("plain", name="P1")
    assert agent["org_role"] == ""
