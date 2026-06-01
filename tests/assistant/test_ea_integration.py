from __future__ import annotations

from openjarvis.assistant.decisions.store import DecisionLogStore
from openjarvis.assistant.followups.store import FollowUpStore
from openjarvis.core.events import EventBus, EventType
from openjarvis.tools.decision_tools import DecisionRecordTool
from openjarvis.tools.followup_tools import (
    FollowupAddTool,
    FollowupListTool,
    FollowupSweepStaleTool,
)


def test_followup_lifecycle_emits_events(monkeypatch, tmp_path):
    bus = EventBus(record_history=True)
    fstore = FollowUpStore(db_path=str(tmp_path / "f.db"), bus=bus)
    monkeypatch.setattr(
        "openjarvis.tools.followup_tools._followup_store", lambda: fstore
    )

    add = FollowupAddTool().execute(
        summary="Lance needs SQL validation",
        counterparty="Lance",
        direction="waiting_on",
        sla_due_at=100.0,
    )
    assert add.success is True
    # Force staleness via the sweep tool's now override.
    swept = FollowupSweepStaleTool().execute(now=1_000_000.0)
    assert swept.metadata["count"] == 1
    listed = FollowupListTool().execute(status="nudged")
    assert "Lance" in listed.content
    assert any(e.event_type == EventType.FOLLOWUP_CREATED for e in bus.history)
    assert any(e.event_type == EventType.FOLLOWUP_UPDATED for e in bus.history)


def test_decision_linked_to_task(monkeypatch, tmp_path):
    dstore = DecisionLogStore(db_path=str(tmp_path / "d.db"))
    monkeypatch.setattr(
        "openjarvis.tools.decision_tools._decision_store", lambda: dstore
    )
    rec = DecisionRecordTool().execute(
        statement="Approve SQL schema v2",
        decided_by="user",
        approved_by="user",
        linked_task_id="task-42",
    )
    assert rec.success is True
    assert dstore.list(linked_task_id="task-42")[0].statement == "Approve SQL schema v2"
