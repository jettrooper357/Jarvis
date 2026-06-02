from __future__ import annotations

from openjarvis.lifemanager.store import LifeStore
from openjarvis.tools.lifemanager_tools import (
    LifeAddDomainTool,
    LifeAddRoutineTool,
    LifeCompleteRoutineTool,
    LifeDueTool,
    LifeListTool,
)


def _store(monkeypatch, tmp_path):
    store = LifeStore(db_path=str(tmp_path / "life.db"))
    monkeypatch.setattr(
        "openjarvis.tools.lifemanager_tools._life_store", lambda: store
    )
    return store


def test_add_domain_routine_complete_due_flow(monkeypatch, tmp_path):
    _store(monkeypatch, tmp_path)
    dom = LifeAddDomainTool().execute(name="Health")
    assert dom.success is True
    domain_id = dom.metadata["domain_id"]

    add = LifeAddRoutineTool().execute(
        title="Walk", domain_id=domain_id, cadence="daily"
    )
    assert add.success is True

    comp = LifeCompleteRoutineTool().execute(
        routine_id=add.metadata["routine_id"]
    )
    assert comp.success is True
    assert "streak" in comp.content.lower()

    listed = LifeListTool().execute(domain_id=domain_id)
    assert listed.success is True
    assert "Walk" in listed.content


def test_due_tool_surfaces_owed(monkeypatch, tmp_path):
    store = _store(monkeypatch, tmp_path)
    r = store.add_routine(title="owed", cadence="daily", now=1.0)
    store.complete_routine(r.id, now=1.0)
    res = LifeDueTool().execute(now=500000.0)
    assert res.success is True
    assert "owed" in res.content


def test_add_routine_requires_title(monkeypatch, tmp_path):
    _store(monkeypatch, tmp_path)
    res = LifeAddRoutineTool().execute(title="  ", cadence="daily")
    assert res.success is False


def test_add_routine_bad_cadence_returns_failure(monkeypatch, tmp_path):
    _store(monkeypatch, tmp_path)
    res = LifeAddRoutineTool().execute(title="x", cadence="hourly")
    assert res.success is False
