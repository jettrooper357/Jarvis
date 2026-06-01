from __future__ import annotations

from openjarvis.assistant.decisions.store import Decision, DecisionLogStore
from openjarvis.core.events import EventBus, EventType


def _store(tmp_path, bus=None):
    return DecisionLogStore(db_path=str(tmp_path / "decisions.db"), bus=bus)


def test_record_and_list(tmp_path):
    bus = EventBus(record_history=True)
    store = _store(tmp_path, bus)
    d = store.record(
        statement="Ship EA Phase 1 behind a flag",
        rationale="Lowest regression risk",
        decided_by="user",
        approved_by="user",
        linked_project_id="proj-1",
        now=1000.0,
    )
    assert isinstance(d, Decision)
    assert d.status == "active"
    assert d.decided_at == 1000.0
    listed = store.list(linked_project_id="proj-1")
    assert len(listed) == 1
    assert listed[0].statement == "Ship EA Phase 1 behind a flag"
    assert any(e.event_type == EventType.DECISION_RECORDED for e in bus.history)
    store.close()


def test_supersede(tmp_path):
    store = _store(tmp_path)
    old = store.record(
        statement="Use Postgres", rationale="r1", decided_by="user", now=1.0
    )
    new = store.record(
        statement="Use SQLite",
        rationale="local-first",
        decided_by="user",
        supersedes=old.id,
        now=2.0,
    )
    assert new.supersedes == old.id
    assert store.get(old.id).status == "superseded"
    active = store.list(status="active")
    assert active == [new] or active[0].id == new.id
    store.close()


def test_record_requires_statement(tmp_path):
    store = _store(tmp_path)
    import pytest

    with pytest.raises(ValueError):
        store.record(statement="  ", rationale="x", decided_by="user")
    store.close()
