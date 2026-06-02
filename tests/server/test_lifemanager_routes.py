from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from openjarvis.lifemanager.store import LifeStore
from openjarvis.server.lifemanager_routes import lifemanager_router


def _client(store):
    app = FastAPI()
    app.include_router(lifemanager_router)
    app.state.life_store = store
    return TestClient(app)


def test_domain_and_routine_crud(tmp_path):
    store = LifeStore(db_path=str(tmp_path / "life.db"))
    client = _client(store)
    r = client.post("/v1/life/domains", json={"name": "Health"})
    assert r.status_code == 200
    domain_id = r.json()["id"]
    assert r.json()["slug"] == "health"

    r = client.get("/v1/life/domains")
    assert len(r.json()["domains"]) == 1

    r = client.post(
        "/v1/life/routines",
        json={"title": "Walk", "domain_id": domain_id, "cadence": "daily"},
    )
    assert r.status_code == 200
    routine_id = r.json()["id"]

    r = client.get("/v1/life/routines", params={"domain_id": domain_id})
    assert len(r.json()["routines"]) == 1

    r = client.post(f"/v1/life/routines/{routine_id}/complete")
    assert r.status_code == 200
    assert r.json()["streak"] == 1
    store.close()


def test_due_endpoint(tmp_path):
    store = LifeStore(db_path=str(tmp_path / "life.db"))
    rr = store.add_routine(title="owed", cadence="daily", now=1.0)
    store.complete_routine(rr.id, now=1.0)
    client = _client(store)
    r = client.get("/v1/life/due", params={"now": 500000.0})
    assert r.status_code == 200
    titles = [x["title"] for x in r.json()["routines"]]
    assert "owed" in titles
    store.close()


def test_complete_missing_returns_409(tmp_path):
    store = LifeStore(db_path=str(tmp_path / "life.db"))
    client = _client(store)
    r = client.post("/v1/life/routines/nope/complete")
    assert r.status_code == 409
    store.close()


def test_missing_store_reads_empty_writes_503():
    app = FastAPI()
    app.include_router(lifemanager_router)
    client = TestClient(app)
    assert client.get("/v1/life/domains").json() == {"domains": []}
    assert client.get("/v1/life/routines").json() == {"routines": []}
    assert client.get("/v1/life/due").json() == {"routines": []}
    assert client.post("/v1/life/domains", json={"name": "x"}).status_code == 503
