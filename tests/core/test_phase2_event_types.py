"""Phase 2A — new EventType values exist and the bus dispatches them.

Wired emitters land in Phase 2C (task.*) and Phase 2D (approval.*); this
test just locks in the enum surface so a downstream rename can't silently
shift the wire protocol.
"""

from __future__ import annotations

from openjarvis.core.events import Event, EventBus, EventType

PHASE_2A_NEW_TYPES = (
    EventType.TASK_CREATED,
    EventType.TASK_UPDATED,
    EventType.TASK_DELEGATED,
    EventType.TASK_COMPLETED,
    EventType.TASK_FAILED,
    EventType.APPROVAL_REQUESTED,
    EventType.APPROVAL_RESOLVED,
    EventType.UI_NOTIFICATION,
)


def test_new_event_type_values_match_wire_strings() -> None:
    expected = {
        "TASK_CREATED": "task.created",
        "TASK_UPDATED": "task.updated",
        "TASK_DELEGATED": "task.delegated",
        "TASK_COMPLETED": "task.completed",
        "TASK_FAILED": "task.failed",
        "APPROVAL_REQUESTED": "approval.requested",
        "APPROVAL_RESOLVED": "approval.resolved",
        "UI_NOTIFICATION": "ui.notification",
    }
    for member, wire in expected.items():
        assert EventType[member].value == wire


def test_subscribe_to_new_event_types_does_not_crash() -> None:
    bus = EventBus(record_history=True)
    received: list[Event] = []
    for event_type in PHASE_2A_NEW_TYPES:
        bus.subscribe(event_type, received.append)
    for event_type in PHASE_2A_NEW_TYPES:
        bus.publish(event_type, {"probe": event_type.value})
    assert len(received) == len(PHASE_2A_NEW_TYPES)
    assert [e.event_type for e in received] == list(PHASE_2A_NEW_TYPES)


def test_history_records_new_events_in_order() -> None:
    bus = EventBus(record_history=True)
    bus.publish(EventType.TASK_CREATED, {"task_id": "a"})
    bus.publish(EventType.APPROVAL_REQUESTED, {"approval_id": "b"})
    bus.publish(EventType.TASK_COMPLETED, {"task_id": "a"})
    types = [e.event_type for e in bus.history]
    assert types == [
        EventType.TASK_CREATED,
        EventType.APPROVAL_REQUESTED,
        EventType.TASK_COMPLETED,
    ]
