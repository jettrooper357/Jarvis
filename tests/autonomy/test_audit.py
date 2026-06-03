from __future__ import annotations

from openjarvis.autonomy.audit import build_audit_report
from openjarvis.core.events import Event, EventType
from openjarvis.eventlog.store import EventLogStore


def test_report_over_window_and_filter(tmp_path):
    store = EventLogStore(db_path=str(tmp_path / "events.db"))
    store.record(
        Event(EventType.TASK_CREATED, 100.0, {"task_id": "t1", "agent_id": "a1"})
    )
    store.record(
        Event(EventType.TASK_UPDATED, 200.0, {"task_id": "t1", "agent_id": "a2"})
    )
    report = build_audit_report(store)
    assert report["count"] == 2
    assert len(report["events"]) == 2
    filtered = build_audit_report(store, agent_id="a1")
    assert filtered["count"] == 1
    assert filtered["events"][0]["agent_id"] == "a1"
    store.close()


def test_report_none_store_is_graceful():
    report = build_audit_report(None)
    assert report["events"] == []
    assert report["count"] == 0
    assert "note" in report
