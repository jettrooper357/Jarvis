from __future__ import annotations

from openjarvis.assistant.followups.store import FollowUp, FollowUpStore
from openjarvis.core.events import EventBus, EventType


def _store(tmp_path, bus=None):
    return FollowUpStore(db_path=str(tmp_path / "followups.db"), bus=bus)


def test_add_and_get(tmp_path):
    bus = EventBus(record_history=True)
    store = _store(tmp_path, bus)
    fu = store.add(
        summary="Reply to Jon re SQL validation",
        counterparty="Jon",
        direction="owe_reply",
        now=1000.0,
    )
    assert isinstance(fu, FollowUp)
    assert fu.status == "open"
    assert fu.created_at == 1000.0
    fetched = store.get(fu.id)
    assert fetched is not None
    assert fetched.summary == "Reply to Jon re SQL validation"
    assert any(e.event_type == EventType.FOLLOWUP_CREATED for e in bus.history)
    store.close()


def test_add_rejects_bad_direction(tmp_path):
    store = _store(tmp_path)
    import pytest

    with pytest.raises(ValueError):
        store.add(summary="x", counterparty="y", direction="sideways")
    store.close()


def test_list_filters(tmp_path):
    store = _store(tmp_path)
    store.add(summary="a", counterparty="Nate", direction="waiting_on", now=1.0)
    store.add(summary="b", counterparty="Jon", direction="owe_reply", now=2.0)
    assert len(store.list()) == 2
    assert len(store.list(counterparty="Nate")) == 1
    assert store.list(counterparty="Nate")[0].summary == "a"
    store.close()


def test_resolve(tmp_path):
    store = _store(tmp_path)
    fu = store.add(summary="a", counterparty="Nate", now=1.0)
    resolved = store.resolve(fu.id, status="resolved", now=5.0)
    assert resolved is not None
    assert resolved.status == "resolved"
    assert resolved.resolved_at == 5.0
    assert store.list(status="resolved")[0].id == fu.id
    assert store.resolve("missing") is None
    store.close()


def test_sweep_stale(tmp_path):
    store = _store(tmp_path)
    stale = store.add(summary="old", counterparty="Nate", sla_due_at=100.0, now=1.0)
    store.add(summary="fresh", counterparty="Jon", sla_due_at=9999.0, now=1.0)
    nudged = store.sweep_stale(now=500.0)
    assert [f.id for f in nudged] == [stale.id]
    assert store.get(stale.id).status == "nudged"
    # Idempotent: already-nudged items are not returned again.
    assert store.sweep_stale(now=600.0) == []
    store.close()
