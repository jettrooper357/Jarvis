from __future__ import annotations

from openjarvis.assistant.followups.store import FollowUpStore
from openjarvis.tools.followup_tools import (
    FollowupAddTool,
    FollowupListTool,
    FollowupResolveTool,
    FollowupSweepStaleTool,
)


def _store(monkeypatch, tmp_path):
    store = FollowUpStore(db_path=str(tmp_path / "f.db"))
    monkeypatch.setattr(
        "openjarvis.tools.followup_tools._followup_store", lambda: store
    )
    return store


def test_followup_add_and_list(monkeypatch, tmp_path):
    _store(monkeypatch, tmp_path)
    add = FollowupAddTool().execute(
        summary="Reply to Jon", counterparty="Jon", direction="owe_reply"
    )
    assert add.success is True
    assert "Jon" in add.content
    listed = FollowupListTool().execute()
    assert listed.success is True
    assert "Reply to Jon" in listed.content


def test_followup_add_rejects_bad_direction(monkeypatch, tmp_path):
    _store(monkeypatch, tmp_path)
    res = FollowupAddTool().execute(summary="x", counterparty="y", direction="nope")
    assert res.success is False
    assert "direction" in res.content


def test_followup_resolve(monkeypatch, tmp_path):
    store = _store(monkeypatch, tmp_path)
    fu = store.add(summary="a", counterparty="Nate")
    res = FollowupResolveTool().execute(followup_id=fu.id)
    assert res.success is True
    assert store.get(fu.id).status == "resolved"
    missing = FollowupResolveTool().execute(followup_id="nope")
    assert missing.success is False


def test_followup_sweep_stale(monkeypatch, tmp_path):
    store = _store(monkeypatch, tmp_path)
    store.add(summary="old", counterparty="Nate", sla_due_at=100.0, now=1.0)
    res = FollowupSweepStaleTool().execute(now=500.0)
    assert res.success is True
    assert "1" in res.content
    assert res.metadata["count"] == 1


def test_followup_specs_have_confirmation_flags():
    assert FollowupAddTool().spec.requires_confirmation is True
    assert FollowupResolveTool().spec.requires_confirmation is True
    assert FollowupListTool().spec.requires_confirmation is False
