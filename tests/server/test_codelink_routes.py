from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from openjarvis.codelink.context import WorkContext
from openjarvis.codelink.store import CodeLinkStore
from openjarvis.server.codelink_routes import codelink_router


def _client(store):
    app = FastAPI()
    app.include_router(codelink_router)
    app.state.codelink_store = store
    return TestClient(app)


def _seed(store):
    store.record_file_event(path="a.py", change_type="modified", task_id="t1", now=1.0)
    store.record_commit(commit_sha="sha1", repo_path="/r", task_id="t1", now=2.0)


def test_file_events_and_commits(tmp_path):
    WorkContext.clear()
    store = CodeLinkStore(db_path=str(tmp_path / "cl.db"))
    _seed(store)
    client = _client(store)
    r = client.get("/v1/codelink/file-events", params={"task_id": "t1"})
    assert r.status_code == 200
    assert len(r.json()["file_events"]) == 1
    r = client.get("/v1/codelink/commits", params={"task_id": "t1"})
    assert len(r.json()["commits"]) == 1
    store.close()


def test_task_view(tmp_path):
    WorkContext.clear()
    store = CodeLinkStore(db_path=str(tmp_path / "cl.db"))
    _seed(store)
    client = _client(store)
    r = client.get("/v1/codelink/tasks/t1")
    assert r.status_code == 200
    body = r.json()
    assert len(body["file_events"]) == 1
    assert len(body["commits"]) == 1
    store.close()


def test_status_endpoint(tmp_path):
    WorkContext.clear()
    store = CodeLinkStore(db_path=str(tmp_path / "cl.db"))
    client = _client(store)
    r = client.get("/v1/codelink/status")
    assert r.status_code == 200
    assert "watchdog_available" in r.json()
    store.close()


def test_missing_store_returns_empty():
    app = FastAPI()
    app.include_router(codelink_router)
    client = TestClient(app)
    assert client.get("/v1/codelink/file-events").json() == {"file_events": []}
    assert client.get("/v1/codelink/commits").json() == {"commits": []}
