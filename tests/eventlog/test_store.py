from __future__ import annotations

from openjarvis.core.events import Event, EventType
from openjarvis.eventlog.store import EventLogStore, EventRecord


def _store(tmp_path):
    return EventLogStore(db_path=str(tmp_path / "events.db"))


def _event(event_type, data, ts=1000.0):
    return Event(event_type=event_type, timestamp=ts, data=data)


def test_record_and_query_roundtrip(tmp_path):
    store = _store(tmp_path)
    store.record(_event(EventType.TASK_CREATED, {"task_id": "t1", "agent_id": "a1"}))
    rows = store.query()
    assert len(rows) == 1
    rec = rows[0]
    assert isinstance(rec, EventRecord)
    assert rec.event_type == "task.created"
    assert rec.task_id == "t1"
    assert rec.agent_id == "a1"
    assert rec.project_id is None
    assert rec.run_id is None
    assert rec.data == {"task_id": "t1", "agent_id": "a1"}
    assert rec.timestamp == 1000.0
    assert store.count() == 1
    store.close()


def test_id_extraction_aliases_and_missing(tmp_path):
    store = _store(tmp_path)
    store.record(
        _event(
            EventType.AGENT_MESSAGE_RECEIVED,
            {"agent": "a2", "project": "p2", "correlation_id": "r2"},
        )
    )
    rec = store.query()[0]
    assert rec.agent_id == "a2"
    assert rec.project_id == "p2"
    assert rec.run_id == "r2"
    assert rec.task_id is None
    store.close()


def test_non_string_id_becomes_null(tmp_path):
    store = _store(tmp_path)
    store.record(_event(EventType.TASK_UPDATED, {"task_id": {"nested": 1}}))
    rec = store.query()[0]
    assert rec.task_id is None
    assert rec.data == {"task_id": {"nested": 1}}
    store.close()


def test_query_filters_and_ordering(tmp_path):
    store = _store(tmp_path)
    store.record(_event(EventType.TASK_CREATED, {"task_id": "t1"}, ts=1.0))
    store.record(_event(EventType.TASK_UPDATED, {"task_id": "t1"}, ts=2.0))
    store.record(_event(EventType.TASK_CREATED, {"task_id": "t2"}, ts=3.0))
    assert len(store.query(event_type="task.created")) == 2
    assert len(store.query(task_id="t1")) == 2
    assert len(store.query(since=2.0)) == 2
    assert len(store.query(until=1.0)) == 1
    assert store.query()[0].timestamp == 3.0
    assert len(store.query(limit=1)) == 1
    store.close()


def test_feed_newest_first(tmp_path):
    store = _store(tmp_path)
    store.record(_event(EventType.TASK_CREATED, {"task_id": "t1"}, ts=1.0))
    store.record(_event(EventType.TASK_CREATED, {"task_id": "t2"}, ts=2.0))
    feed = store.feed(limit=10)
    assert [r.task_id for r in feed] == ["t2", "t1"]
    assert len(store.feed(limit=1)) == 1
    store.close()


def test_non_serializable_payload_is_stored(tmp_path):
    from openjarvis.core.types import Trace

    store = _store(tmp_path)
    trace = Trace(trace_id="x1", query="hi")
    store.record(_event(EventType.TRACE_COMPLETE, {"trace": trace, "run_id": "r9"}))
    rec = store.query()[0]
    assert rec.run_id == "r9"
    assert isinstance(rec.data["trace"], str)
    assert "Trace" in rec.data["trace"]
    store.close()


def test_record_swallows_insert_error(tmp_path):
    store = _store(tmp_path)
    store.close()  # closing makes subsequent inserts raise internally
    # Should NOT raise — failure is logged and dropped.
    store.record(_event(EventType.TASK_CREATED, {"task_id": "t1"}))
