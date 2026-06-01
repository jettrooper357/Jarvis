from __future__ import annotations

from openjarvis.core.events import EventType


def test_assistant_event_types_exist():
    assert EventType.FOLLOWUP_CREATED.value == "followup.created"
    assert EventType.FOLLOWUP_UPDATED.value == "followup.updated"
    assert EventType.FOLLOWUP_RESOLVED.value == "followup.resolved"
    assert EventType.DECISION_RECORDED.value == "decision.recorded"
    assert EventType.DECISION_SUPERSEDED.value == "decision.superseded"
