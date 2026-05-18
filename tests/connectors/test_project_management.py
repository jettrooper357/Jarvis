"""Tests for the project-management store and connector.

Covers the SQLite ``ProjectStore`` (CRUD, nested subtasks, progress
roll-up, dashboard analytics, document export, cascade delete) and the
``project_management`` connector (registration, sync, extra-dir ingest).
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from openjarvis.projects.store import ProjectStore


@pytest.fixture
def store(tmp_path: Path) -> ProjectStore:
    s = ProjectStore(tmp_path / "projects.db")
    yield s
    s.close()


# --- projects -----------------------------------------------------------


def test_create_and_get_project_defaults(store: ProjectStore):
    p = store.create_project(name="Apollo")
    assert p["name"] == "Apollo"
    assert p["status"] == "Planning"
    assert p["progress"] == 0
    assert p["team"] == [] and p["tags"] == [] and p["milestones"] == []
    assert store.get_project(p["id"]) == p


def test_get_missing_project_returns_none(store: ProjectStore):
    assert store.get_project("nope") is None


def test_update_project_and_json_fields(store: ProjectStore):
    p = store.create_project(name="Apollo")
    upd = store.update_project(
        p["id"], status="Active", tags=["q3", "infra"], owner="jet"
    )
    assert upd["status"] == "Active"
    assert upd["tags"] == ["q3", "infra"]
    assert upd["owner"] == "jet"


def test_update_missing_project_raises_keyerror(store: ProjectStore):
    with pytest.raises(KeyError):
        store.update_project("nope", status="Active")


def test_list_projects_orders_newest_first(store: ProjectStore):
    a = store.create_project(name="A")
    time.sleep(0.01)
    b = store.create_project(name="B")
    ids = [p["id"] for p in store.list_projects()]
    assert ids[:2] == [b["id"], a["id"]]


# --- tasks / subtasks ---------------------------------------------------


def test_create_task_under_missing_project_raises(store: ProjectStore):
    with pytest.raises(KeyError):
        store.create_task("nope", title="x")


def test_nested_subtasks_and_listing(store: ProjectStore):
    p = store.create_project(name="Apollo")
    t = store.create_task(p["id"], title="Design")
    sub = store.create_task(
        p["id"], title="Wireframes", parent_task_id=t["id"]
    )
    tasks = store.list_tasks(p["id"])
    assert {x["title"] for x in tasks} == {"Design", "Wireframes"}
    child = next(x for x in tasks if x["id"] == sub["id"])
    assert child["parent_task_id"] == t["id"]


def test_progress_rolls_up_from_top_level_tasks(store: ProjectStore):
    p = store.create_project(name="Apollo")
    store.create_task(p["id"], title="T1", percent_complete=40)
    store.create_task(p["id"], title="T2", percent_complete=60)
    # subtask % must NOT affect the roll-up (only top-level tasks count)
    t3 = store.create_task(p["id"], title="T3", percent_complete=0)
    store.create_task(
        p["id"], title="sub", parent_task_id=t3["id"], percent_complete=100
    )
    assert store.get_project(p["id"])["progress"] == 33  # round((40+60+0)/3)


def test_update_task_dependencies_json(store: ProjectStore):
    p = store.create_project(name="Apollo")
    t = store.create_task(p["id"], title="T")
    upd = store.update_task(t["id"], dependencies=["dep1", "dep2"], status="Done")
    assert upd["dependencies"] == ["dep1", "dep2"]
    assert upd["status"] == "Done"


def test_update_missing_task_raises(store: ProjectStore):
    with pytest.raises(KeyError):
        store.update_task("nope", status="Done")


# --- notes --------------------------------------------------------------


def test_note_crud(store: ProjectStore):
    p = store.create_project(name="Apollo")
    t = store.create_task(p["id"], title="T")
    n = store.add_note(t["id"], content="kickoff", type="Update")
    assert n["content"] == "kickoff" and n["type"] == "Update"
    assert [x["id"] for x in store.list_notes(t["id"])] == [n["id"]]
    store.update_note(n["id"], ai_summary="summarized")
    assert store.list_notes(t["id"])[0]["ai_summary"] == "summarized"
    store.delete_note(n["id"])
    assert store.list_notes(t["id"]) == []


def test_add_note_to_missing_task_raises(store: ProjectStore):
    with pytest.raises(KeyError):
        store.add_note("nope", content="x")


# --- cascade delete -----------------------------------------------------


def test_delete_project_cascades_tasks_and_notes(store: ProjectStore):
    p = store.create_project(name="Apollo")
    t = store.create_task(p["id"], title="T")
    store.add_note(t["id"], content="n")
    store.delete_project(p["id"])
    assert store.get_project(p["id"]) is None
    assert store.list_tasks(p["id"]) == []
    assert store.get_task(t["id"]) is None


def test_delete_parent_task_cascades_subtasks(store: ProjectStore):
    p = store.create_project(name="Apollo")
    t = store.create_task(p["id"], title="parent")
    sub = store.create_task(p["id"], title="child", parent_task_id=t["id"])
    store.delete_task(t["id"])
    assert store.get_task(sub["id"]) is None


# --- analytics ----------------------------------------------------------


def test_dashboard_counts(store: ProjectStore):
    p = store.create_project(name="Apollo", status="Active")
    store.create_task(p["id"], title="A", status="In Progress", assigned_to="jet")
    store.create_task(p["id"], title="B", status="Blocked", assigned_to="jet")
    store.create_task(
        p["id"], title="C", status="In Progress", due_date="2000-01-01"
    )  # overdue
    store.create_task(p["id"], title="D", status="Done")
    d = store.dashboard()
    assert d["projects_total"] == 1
    assert d["projects_active"] == 1
    assert d["tasks_blocked"] == 1
    assert d["tasks_overdue"] == 1
    assert d["tasks_done"] == 1
    assert d["workload_by_assignee"]["jet"] == 2  # Done/Cancelled excluded


def test_export_documents_flattens_tree_and_notes(store: ProjectStore):
    p = store.create_project(name="Apollo", description="moon")
    t = store.create_task(p["id"], title="Design")
    store.create_task(p["id"], title="Wireframes", parent_task_id=t["id"])
    store.add_note(t["id"], content="kickoff done")
    docs = store.export_documents()
    assert len(docs) == 1
    doc = docs[0]
    assert doc["doc_id"] == f"project-{p['id']}"
    assert "Wireframes" in doc["content"]
    assert "kickoff done" in doc["content"]


# --- connector ----------------------------------------------------------


def test_connector_registered():
    # conftest's autouse fixture clears ConnectorRegistry for isolation, so
    # reload the module to re-run its @ConnectorRegistry.register decorator.
    import importlib

    import openjarvis.connectors.project_management as pm
    from openjarvis.core.registry import ConnectorRegistry

    importlib.reload(pm)
    assert "project_management" in list(ConnectorRegistry.keys())
    inst = ConnectorRegistry.create("project_management")
    assert inst.display_name == "Project Management"
    assert inst.auth_type == "local"


def test_connector_sync_yields_documents(tmp_path, monkeypatch):
    import openjarvis.projects.store as store_mod
    from openjarvis.connectors.project_management import (
        ProjectManagementConnector,
    )

    db = tmp_path / "projects.db"
    monkeypatch.setattr(store_mod, "default_db_path", lambda: db)

    seed = ProjectStore(db)
    p = seed.create_project(name="Apollo")
    seed.create_task(p["id"], title="Design")
    seed.close()

    cfg = tmp_path / "pm.json"
    conn = ProjectManagementConnector(config_path=str(cfg))
    assert conn.is_connected() is True
    docs = list(conn.sync())
    assert any(
        d.source == "project_management" and d.doc_type == "project"
        for d in docs
    )
    st = conn.sync_status()
    assert st.items_synced >= 1


def test_connector_ingests_extra_dirs(tmp_path, monkeypatch):
    import openjarvis.projects.store as store_mod
    from openjarvis.connectors.project_management import (
        ProjectManagementConnector,
    )

    db = tmp_path / "projects.db"
    monkeypatch.setattr(store_mod, "default_db_path", lambda: db)
    ProjectStore(db).close()  # empty store

    extra = tmp_path / "extra"
    extra.mkdir()
    (extra / "roadmap.md").write_text("# Roadmap\nShip v1", encoding="utf-8")

    cfg = tmp_path / "pm.json"
    cfg.write_text(
        json.dumps({"extra_project_dirs": [str(extra)]}), encoding="utf-8"
    )
    conn = ProjectManagementConnector(config_path=str(cfg))
    docs = list(conn.sync())
    assert any(
        d.doc_type == "project_file" and "Roadmap" in d.content for d in docs
    )
