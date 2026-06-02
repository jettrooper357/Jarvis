from __future__ import annotations

from openjarvis.core.events import EventBus, EventType
from openjarvis.eventlog.store import EventLogStore


def test_subscribed_store_captures_events(tmp_path):
    bus = EventBus()
    store = EventLogStore(db_path=str(tmp_path / "e.db"))
    store.subscribe_to_bus(bus)
    bus.publish(EventType.TASK_CREATED, {"task_id": "t1", "agent_id": "a1"})
    bus.publish(EventType.AGENT_MESSAGE_RECEIVED, {"agent_id": "a1"})
    assert store.count() == 2
    rows = store.query(task_id="t1")
    assert len(rows) == 1
    assert rows[0].event_type == "task.created"
    store.close()


def test_denylist_skips_subscription(tmp_path):
    bus = EventBus()
    store = EventLogStore(db_path=str(tmp_path / "e.db"))
    store.subscribe_to_bus(bus, denylist=["task.created"])
    bus.publish(EventType.TASK_CREATED, {"task_id": "t1"})
    bus.publish(EventType.TASK_UPDATED, {"task_id": "t1"})
    assert store.count() == 1
    assert store.query()[0].event_type == "task.updated"
    store.close()
