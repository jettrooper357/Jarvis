from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from openjarvis.core.events import Event, EventType
from openjarvis.eventlog.store import EventLogStore
from openjarvis.server.eventlog_routes import eventlog_router


def _client(store):
    app = FastAPI()
    app.include_router(eventlog_router)
    app.state.event_log_store = store
    return TestClient(app)


def _seed(store):
    store.record(
        Event(EventType.TASK_CREATED, 1.0, {"task_id": "t1", "agent_id": "a1"})
    )
    store.record(Event(EventType.TASK_UPDATED, 2.0, {"task_id": "t1"}))


def test_list_events_and_filter(tmp_path):
    store = EventLogStore(db_path=str(tmp_path / "e.db"))
    _seed(store)
    client = _client(store)
    resp = client.get("/v1/events")
    assert resp.status_code == 200
    assert len(resp.json()["events"]) == 2
    resp = client.get("/v1/events", params={"event_type": "task.created"})
    events = resp.json()["events"]
    assert len(events) == 1
    assert events[0]["task_id"] == "t1"
    assert "created_at" in events[0]
    store.close()


def test_feed_endpoint(tmp_path):
    store = EventLogStore(db_path=str(tmp_path / "e.db"))
    _seed(store)
    client = _client(store)
    resp = client.get("/v1/events/feed", params={"limit": 1})
    assert resp.status_code == 200
    assert len(resp.json()["events"]) == 1
    store.close()


def test_missing_store_returns_empty():
    app = FastAPI()
    app.include_router(eventlog_router)
    client = TestClient(app)
    resp = client.get("/v1/events")
    assert resp.status_code == 200
    assert resp.json() == {"events": []}
