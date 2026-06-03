from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from openjarvis.autonomy.rollback_store import RollbackStore
from openjarvis.core.events import Event, EventType
from openjarvis.eventlog.store import EventLogStore
from openjarvis.server.autonomy_routes import autonomy_router


def _client(rollback=None, eventlog=None):
    app = FastAPI()
    app.include_router(autonomy_router)
    if rollback is not None:
        app.state.rollback_store = rollback
    if eventlog is not None:
        app.state.event_log_store = eventlog
    return TestClient(app)


def test_record_list_get_revert(tmp_path):
    store = RollbackStore(db_path=str(tmp_path / "auto.db"))
    f = tmp_path / "a.txt"
    f.write_text("new", encoding="utf-8")
    client = _client(rollback=store)
    r = client.post(
        "/v1/rollback",
        json={
            "action_type": "file_write",
            "summary": "wrote a",
            "undo_payload": {"path": str(f), "prior_content": "old"},
        },
    )
    assert r.status_code == 200
    aid = r.json()["id"]
    assert r.json()["status"] == "active"

    assert len(client.get("/v1/rollback").json()["actions"]) == 1
    assert client.get(f"/v1/rollback/{aid}").status_code == 200
    assert client.get("/v1/rollback/nope").status_code == 404

    rev = client.post(f"/v1/rollback/{aid}/revert", json={})
    assert rev.status_code == 200
    assert rev.json()["status"] == "reverted"
    assert f.read_text(encoding="utf-8") == "old"
    assert client.post(f"/v1/rollback/{aid}/revert", json={}).status_code == 409
    store.close()


def test_audit_report_endpoint(tmp_path):
    elog = EventLogStore(db_path=str(tmp_path / "events.db"))
    elog.record(Event(EventType.TASK_CREATED, 1.0, {"task_id": "t1"}))
    client = _client(eventlog=elog)
    r = client.get("/v1/audit/report")
    assert r.status_code == 200
    assert r.json()["count"] == 1
    elog.close()


def test_missing_stores(tmp_path):
    client = _client()
    assert client.get("/v1/rollback").json() == {"actions": []}
    assert client.post(
        "/v1/rollback", json={"action_type": "file_write", "summary": "x"}
    ).status_code == 503
    assert client.get("/v1/audit/report").json()["count"] == 0
