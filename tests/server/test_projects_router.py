"""Tests for the /v1/projects API router (FastAPI TestClient).

The router holds a lazy module-level ProjectStore singleton; the fixture
points it at a tmp DB so tests never touch the user's real store.
"""

from __future__ import annotations

import pytest


@pytest.fixture
def client(tmp_path, monkeypatch):
    try:
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
    except ImportError:
        pytest.skip("fastapi not installed")

    import openjarvis.server.projects_router as pr
    from openjarvis.projects.store import ProjectStore

    store = ProjectStore(tmp_path / "projects.db")
    monkeypatch.setattr(pr, "_store", store)

    app = FastAPI()
    app.include_router(pr.create_projects_router())
    yield TestClient(app)
    store.close()


def _new_project(client, **kw):
    body = {"name": "Apollo", **kw}
    r = client.post("/v1/projects", json=body)
    assert r.status_code == 200, r.text
    return r.json()


# --- projects -----------------------------------------------------------


def test_project_crud_lifecycle(client):
    assert client.get("/v1/projects").json() == {"projects": []}

    p = _new_project(client, owner="jet", status="Active")
    pid = p["id"]
    assert p["name"] == "Apollo" and p["status"] == "Active"

    assert client.get(f"/v1/projects/{pid}").json()["owner"] == "jet"

    upd = client.put(f"/v1/projects/{pid}", json={"status": "Complete"})
    assert upd.status_code == 200
    assert upd.json()["status"] == "Complete"

    listed = client.get("/v1/projects").json()["projects"]
    assert len(listed) == 1

    d = client.delete(f"/v1/projects/{pid}")
    assert d.status_code == 200 and d.json()["deleted"] is True
    assert client.get("/v1/projects").json() == {"projects": []}


def test_get_missing_project_404(client):
    assert client.get("/v1/projects/nope").status_code == 404


def test_update_missing_project_404(client):
    r = client.put("/v1/projects/nope", json={"status": "Active"})
    assert r.status_code == 404


def test_create_project_rejects_non_object_body(client):
    r = client.post("/v1/projects", json=["not", "an", "object"])
    assert r.status_code == 400


# --- tasks / subtasks ---------------------------------------------------


def test_task_and_subtask_endpoints(client):
    pid = _new_project(client)["id"]

    t = client.post(
        f"/v1/projects/{pid}/tasks", json={"title": "Design"}
    ).json()
    sub = client.post(
        f"/v1/projects/{pid}/tasks",
        json={"title": "Wireframes", "parent_task_id": t["id"]},
    ).json()
    assert sub["parent_task_id"] == t["id"]

    tasks = client.get(f"/v1/projects/{pid}/tasks").json()["tasks"]
    assert len(tasks) == 2

    upd = client.put(
        f"/v1/projects/tasks/{t['id']}",
        json={"status": "Done", "percent_complete": 100},
    )
    assert upd.status_code == 200
    assert upd.json()["status"] == "Done"

    d = client.delete(f"/v1/projects/tasks/{sub['id']}")
    assert d.status_code == 200
    assert len(client.get(f"/v1/projects/{pid}/tasks").json()["tasks"]) == 1


def test_create_task_missing_project_404(client):
    r = client.post("/v1/projects/nope/tasks", json={"title": "x"})
    assert r.status_code == 404


def test_update_missing_task_404(client):
    r = client.put("/v1/projects/tasks/nope", json={"status": "Done"})
    assert r.status_code == 404


# --- notes --------------------------------------------------------------


def test_note_endpoints(client):
    pid = _new_project(client)["id"]
    tid = client.post(
        f"/v1/projects/{pid}/tasks", json={"title": "T"}
    ).json()["id"]

    n = client.post(
        f"/v1/projects/tasks/{tid}/notes",
        json={"content": "kickoff", "type": "Update"},
    ).json()
    assert n["content"] == "kickoff"

    notes = client.get(f"/v1/projects/tasks/{tid}/notes").json()["notes"]
    assert len(notes) == 1

    upd = client.put(
        f"/v1/projects/notes/{n['id']}", json={"content": "edited"}
    )
    assert upd.status_code == 200 and upd.json()["content"] == "edited"

    assert client.delete(f"/v1/projects/notes/{n['id']}").status_code == 200
    assert client.get(f"/v1/projects/tasks/{tid}/notes").json() == {
        "notes": []
    }


def test_add_note_missing_task_404(client):
    r = client.post(
        "/v1/projects/tasks/nope/notes", json={"content": "x"}
    )
    assert r.status_code == 404


# --- analytics / AI -----------------------------------------------------


def test_dashboard_endpoint(client):
    pid = _new_project(client, status="Active")["id"]
    client.post(
        f"/v1/projects/{pid}/tasks",
        json={"title": "A", "status": "Blocked"},
    )
    d = client.get("/v1/projects/dashboard").json()
    assert d["projects_total"] == 1
    assert d["tasks_blocked"] == 1
    # /dashboard must resolve before /{project_id} (route ordering)
    assert "workload_by_assignee" in d


def test_ai_summary_heuristic_fallback(client):
    """No engine on app.state -> deterministic heuristic summary."""
    pid = _new_project(client)["id"]
    client.post(
        f"/v1/projects/{pid}/tasks",
        json={"title": "A", "status": "Blocked"},
    )
    r = client.post(f"/v1/projects/{pid}/ai-summary", json={})
    assert r.status_code == 200
    body = r.json()
    assert body["project_id"] == pid
    assert "heuristic" in body["summary"].lower()


def test_ai_summary_missing_project_404(client):
    r = client.post("/v1/projects/nope/ai-summary", json={})
    assert r.status_code == 404
