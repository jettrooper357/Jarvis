from __future__ import annotations

from openjarvis.agents.library import list_templates


def _by_id(templates, tid):
    return next((t for t in templates if t.get("id") == tid), None)


def test_decision_recorder_template_present_and_valid():
    t = _by_id(list_templates(), "decision_recorder")
    assert t is not None
    assert "decision_record" in t["tools"]
    assert t["agent_type"]


def test_priority_advisor_template_present_and_valid():
    t = _by_id(list_templates(), "priority_advisor")
    assert t is not None
    assert "followup_list" in t["tools"]
    assert t["agent_type"]
