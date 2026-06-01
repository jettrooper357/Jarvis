from __future__ import annotations

from openjarvis.assistant.decisions.store import DecisionLogStore
from openjarvis.tools.decision_tools import DecisionListTool, DecisionRecordTool


def _store(monkeypatch, tmp_path):
    store = DecisionLogStore(db_path=str(tmp_path / "d.db"))
    monkeypatch.setattr(
        "openjarvis.tools.decision_tools._decision_store", lambda: store
    )
    return store


def test_decision_record_and_list(monkeypatch, tmp_path):
    _store(monkeypatch, tmp_path)
    rec = DecisionRecordTool().execute(
        statement="Ship behind a flag",
        rationale="safety",
        decided_by="user",
        linked_project_id="p1",
    )
    assert rec.success is True
    assert "decision_id" in rec.metadata
    listed = DecisionListTool().execute(linked_project_id="p1")
    assert listed.success is True
    assert "Ship behind a flag" in listed.content


def test_decision_record_requires_statement(monkeypatch, tmp_path):
    _store(monkeypatch, tmp_path)
    res = DecisionRecordTool().execute(statement="  ")
    assert res.success is False


def test_decision_record_requires_confirmation():
    assert DecisionRecordTool().spec.requires_confirmation is True
    assert DecisionListTool().spec.requires_confirmation is False
