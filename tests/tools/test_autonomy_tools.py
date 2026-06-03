from __future__ import annotations

from openjarvis.autonomy.rollback_store import RollbackStore
from openjarvis.core.events import Event, EventType
from openjarvis.eventlog.store import EventLogStore
from openjarvis.tools.autonomy_tools import (
    AuditReportTool,
    RollbackListTool,
    RollbackRecordTool,
    RollbackRevertTool,
)


def _store(monkeypatch, tmp_path):
    store = RollbackStore(db_path=str(tmp_path / "auto.db"))
    monkeypatch.setattr(
        "openjarvis.tools.autonomy_tools._rollback_store", lambda: store
    )
    return store


def test_record_list_revert_flow(monkeypatch, tmp_path):
    _store(monkeypatch, tmp_path)
    f = tmp_path / "a.txt"
    f.write_text("new", encoding="utf-8")
    rec = RollbackRecordTool().execute(
        action_type="file_write",
        summary="wrote a",
        undo_payload={"path": str(f), "prior_content": "old"},
    )
    assert rec.success is True
    aid = rec.metadata["action_id"]

    listed = RollbackListTool().execute()
    assert listed.success is True
    assert "wrote a" in listed.content

    rev = RollbackRevertTool().execute(action_id=aid)
    assert rev.success is True
    assert f.read_text(encoding="utf-8") == "old"


def test_revert_missing_returns_failure(monkeypatch, tmp_path):
    _store(monkeypatch, tmp_path)
    res = RollbackRevertTool().execute(action_id="nope")
    assert res.success is False


def test_audit_report_tool(monkeypatch, tmp_path):
    elog = EventLogStore(db_path=str(tmp_path / "events.db"))
    elog.record(Event(EventType.TASK_CREATED, 1.0, {"task_id": "t1"}))
    monkeypatch.setattr(
        "openjarvis.tools.autonomy_tools._event_log_store", lambda: elog
    )
    res = AuditReportTool().execute()
    assert res.success is True
    assert "task.created" in res.content or "1" in res.content
