from __future__ import annotations

from openjarvis.codelink.context import WorkContext
from openjarvis.codelink.store import CodeLinkStore
from openjarvis.tools.codelink_tools import (
    CodeLinkQueryTool,
    CodeLinkRecordFileEventTool,
    CodeLinkSetWorkContextTool,
)


def _store(monkeypatch, tmp_path):
    store = CodeLinkStore(db_path=str(tmp_path / "cl.db"))
    monkeypatch.setattr(
        "openjarvis.tools.codelink_tools._codelink_store", lambda: store
    )
    return store


def test_set_context_then_record(monkeypatch, tmp_path):
    WorkContext.clear()
    store = _store(monkeypatch, tmp_path)
    ctx = CodeLinkSetWorkContextTool().execute(task_id="t1", agent_id="a1")
    assert ctx.success is True

    rec = CodeLinkRecordFileEventTool().execute(
        path="src/x.py", change_type="modified"
    )
    assert rec.success is True
    events = store.file_events(task_id="t1")
    assert len(events) == 1
    assert events[0].agent_id == "a1"
    WorkContext.clear()
    store.close()


def test_query_by_task(monkeypatch, tmp_path):
    WorkContext.clear()
    store = _store(monkeypatch, tmp_path)
    store.record_file_event(path="a.py", change_type="modified", task_id="t9")
    res = CodeLinkQueryTool().execute(task_id="t9")
    assert res.success is True
    assert "a.py" in res.content
    WorkContext.clear()
    store.close()


def test_record_file_event_requires_path(monkeypatch, tmp_path):
    WorkContext.clear()
    _store(monkeypatch, tmp_path)
    res = CodeLinkRecordFileEventTool().execute(path="  ", change_type="modified")
    assert res.success is False
    WorkContext.clear()
