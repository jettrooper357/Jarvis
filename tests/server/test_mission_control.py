"""Tests for Mission Control: agent-task <-> project-task linkage,
the 3-tier role authorization, the runtime writeback, the migration
backfill, and the /v1/projects/mission-control aggregation endpoint.
"""

from __future__ import annotations

import sqlite3
import time
import uuid

import pytest

from openjarvis.agents.manager import _UNASSIGNED_PROJECT_NAME, AgentManager
from openjarvis.projects import authz
from openjarvis.projects.store import ProjectStore


@pytest.fixture
def stores(tmp_path):
    ps = ProjectStore(tmp_path / "projects.db")
    m = AgentManager(str(tmp_path / "agents.db"), project_store=ps)
    yield ps, m
    m.close()
    ps.close()


# --- hard linkage requirement ------------------------------------------


def test_create_task_requires_valid_project_task(stores):
    ps, m = stores
    proj = ps.create_project(name="P", status="Active")
    ptask = ps.create_task(proj["id"], title="Build")
    ag = m.create_agent(name="A", agent_type="monitor_operative")

    orphan = m.create_task(ag["id"], description="orphan")
    assert orphan["project_task_id"]
    assert orphan["project_id"]

    with pytest.raises(ValueError, match="not found"):
        m.create_task(ag["id"], description="bad", project_task_id="nope")

    t = m.create_task(
        ag["id"], description="real", project_task_id=ptask["id"]
    )
    assert t["project_task_id"] == ptask["id"]
    assert t["project_id"] == proj["id"]


def test_backfill_links_unlinked_tasks(stores, tmp_path):
    ps, m = stores
    ag = m.create_agent(name="Legacy", agent_type="monitor_operative")
    # Inject a pre-migration row directly (no project link).
    conn = sqlite3.connect(str(tmp_path / "agents.db"))
    conn.execute(
        "INSERT INTO agent_tasks (id, agent_id, description, status, "
        "created_at) VALUES (?,?,?,?,?)",
        (uuid.uuid4().hex[:12], ag["id"], "old work", "pending", time.time()),
    )
    conn.commit()
    conn.close()

    m2 = AgentManager(str(tmp_path / "agents.db"), project_store=ps)
    try:
        task = next(
            t for t in m2.list_tasks(ag["id"]) if t["description"] == "old work"
        )
        assert task["project_task_id"]
        sys_projects = [
            p
            for p in ps.list_projects()
            if p["name"] == _UNASSIGNED_PROJECT_NAME
        ]
        assert len(sys_projects) == 1
        assert "needs-reconciliation" in sys_projects[0]["tags"]
    finally:
        m2.close()


def test_new_unassigned_agent_work_creates_child_project_task(stores):
    ps, m = stores
    agent = m.create_agent(name="Workflow Manager", agent_type="monitor_operative")
    unassigned = ps.create_project(name=_UNASSIGNED_PROJECT_NAME, status="Active")
    catchall = ps.create_task(
        unassigned["id"],
        title="Unreconciled work — Workflow Manager",
        description="Catch-all",
        type="Chore",
        assigned_to="Workflow Manager",
    )

    task = m.create_task(
        agent["id"],
        description="Start a new project called test project",
        status="active",
        project_task_id=catchall["id"],
    )

    assert task["project_task_id"] != catchall["id"]
    child = ps.get_task(task["project_task_id"])
    assert child["parent_task_id"] == catchall["id"]
    assert child["title"] == "Start a new project called test project"
    assert child["status"] == "In Progress"


# --- 3-tier authorization ----------------------------------------------


def test_role_classification():
    assert authz.classify({"org_role": "Project Manager",
                            "manager_agent_id": "x"}) == authz.ROLE_MANAGER
    # top of org chart (no manager) -> manager tier
    assert authz.classify({"org_role": "",
                            "manager_agent_id": None}) == authz.ROLE_MANAGER
    assert authz.classify({"org_role": "Operative",
                            "manager_agent_id": "m"}) == authz.ROLE_WORKER
    # function-first: QA beats the "lead" manager keyword
    assert authz.classify({"org_role": "QA Lead",
                            "manager_agent_id": "m"}) == authz.ROLE_QA
    assert authz.classify(None) == authz.ROLE_WORKER


def test_permission_matrix():
    mgr = {"id": "m", "name": "PM", "org_role": "Manager",
           "manager_agent_id": "b"}
    wkr = {"id": "w", "name": "Worker A", "org_role": "Operative",
           "manager_agent_id": "m"}
    qa = {"id": "q", "name": "QA", "org_role": "QA", "manager_agent_id": "m"}
    own = {"id": "pt1", "assigned_to": "Worker A"}
    other = {"id": "pt2", "assigned_to": "Someone"}

    assert authz.can(mgr, "project.delete")
    assert authz.can(mgr, "task.reassign", other)

    assert not authz.can(wkr, "project.create")
    assert authz.can(wkr, "task.update", own)
    assert not authz.can(wkr, "task.update", other)
    assert authz.can(wkr, "note.add")

    assert authz.can(qa, "qa.passfail", own)
    assert authz.can(qa, "qa.file_bug", own)
    assert not authz.can(qa, "project.create")
    assert not authz.can(qa, "task.reassign", own)

    with pytest.raises(PermissionError):
        authz.authorize(wkr, "project.delete")


# --- runtime writeback --------------------------------------------------


def _runtime(manager):
    from openjarvis.server.managed_agent_runtime import ManagedAgentRuntime

    return ManagedAgentRuntime(manager=manager, engine=None)


def test_runtime_writeback_worker_owns_leaf(stores):
    ps, m = stores
    proj = ps.create_project(name="P", status="Active")
    pt = ps.create_task(
        proj["id"], title="Ship", status="Backlog", assigned_to="Worker A"
    )
    boss = m.create_agent(name="Boss", agent_type="monitor_operative",
                          org_role="Project Manager")
    w = m.create_agent(name="Worker A", agent_type="monitor_operative",
                       org_role="Operative", manager_agent_id=boss["id"])
    m.create_task(w["id"], description="impl",
                  project_task_id=pt["id"], status="active")
    rt = _runtime(m)

    rt._project_writeback(w, phase="start", summary="go")
    assert ps.get_task(pt["id"])["status"] == "In Progress"

    rt._project_writeback(w, phase="finish", summary="done", error=False)
    after = ps.get_task(pt["id"])
    assert after["status"] == "Done" and after["percent_complete"] == 100
    assert len(ps.list_notes(pt["id"])) == 2


def test_runtime_writeback_error_blocks(stores):
    ps, m = stores
    proj = ps.create_project(name="P", status="Active")
    pt = ps.create_task(proj["id"], title="X", status="In Progress",
                        assigned_to="Worker A")
    boss = m.create_agent(name="B", org_role="Manager")
    w = m.create_agent(name="Worker A", org_role="Operative",
                       manager_agent_id=boss["id"])
    m.create_task(w["id"], description="d",
                  project_task_id=pt["id"], status="active")
    _runtime(m)._project_writeback(w, phase="finish", summary="boom",
                                   error=True)
    assert ps.get_task(pt["id"])["status"] == "Blocked"


def test_runtime_writeback_qa_cannot_autocomplete(stores):
    ps, m = stores
    proj = ps.create_project(name="P", status="Active")
    pt = ps.create_task(proj["id"], title="Verify", status="In Progress",
                        assigned_to="QA Bot")
    boss = m.create_agent(name="B", org_role="Manager")
    qa = m.create_agent(name="QA Bot", org_role="QA Tester",
                        manager_agent_id=boss["id"])
    m.create_task(qa["id"], description="t",
                  project_task_id=pt["id"], status="active")
    _runtime(m)._project_writeback(qa, phase="finish", summary="ok",
                                   error=False)
    ptq = ps.get_task(pt["id"])
    assert ptq["status"] == "In Progress"  # QA must not flip to Done
    assert len(ps.list_notes(pt["id"])) == 1  # but a note is recorded


# --- aggregation endpoint + run linkage --------------------------------


@pytest.fixture
def client(tmp_path, monkeypatch):
    try:
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
    except ImportError:
        pytest.skip("fastapi not installed")

    import openjarvis.server.projects_router as pr

    ps = ProjectStore(tmp_path / "projects.db")
    m = AgentManager(str(tmp_path / "agents.db"), project_store=ps)
    monkeypatch.setattr(pr, "_store", ps)

    app = FastAPI()
    app.state.agent_manager = m
    app.include_router(pr.create_projects_router())
    yield TestClient(app), ps, m
    m.close()
    ps.close()


def test_mission_control_endpoint(client):
    tc, ps, m = client
    proj = ps.create_project(name="MX", status="Active")
    parent = ps.create_task(proj["id"], title="Build", status="In Progress")
    child = ps.create_task(proj["id"], title="Sub", status="Backlog",
                           parent_task_id=parent["id"])
    boss = m.create_agent(name="PM", org_role="Project Manager")
    w = m.create_agent(name="Worker A", org_role="Operative",
                       manager_agent_id=boss["id"])
    # Genuinely working: running WITH a fresh heartbeat.
    m.update_agent(w["id"], status="running", current_activity="coding",
                   last_activity_at=time.time())
    m.create_task(w["id"], description="do sub",
                  project_task_id=child["id"], status="active")

    data = tc.get("/v1/projects/mission-control").json()
    assert {"kpis", "projects", "agents"} <= data.keys()
    root = data["projects"][0]["tasks"][0]
    assert root["title"] == "Build"
    assert root["subtasks"][0]["title"] == "Sub"
    linked = root["subtasks"][0]["linked_agents"]
    assert linked[0]["agent_name"] == "Worker A"
    assert linked[0]["working"] is True
    roster = {a["name"]: a for a in data["agents"]}
    assert roster["PM"]["role_tier"] == "manager"
    assert roster["Worker A"]["working"] is True
    assert roster["Worker A"]["stale"] is False
    assert roster["Worker A"]["linked_project_task_id"] == child["id"]


def test_mission_control_stale_running_agent_not_working(client):
    """A 'running' agent with no recent heartbeat is stale, not working."""
    tc, ps, m = client
    proj = ps.create_project(name="P", status="Active")
    pt = ps.create_task(proj["id"], title="T")
    ag = m.create_agent(name="Zombie", org_role="Operative")
    m.create_task(ag["id"], description="x", project_task_id=pt["id"])
    # Interrupted run: status stuck running, stale heartbeat.
    m.update_agent(ag["id"], status="running",
                   current_activity="Generating response...",
                   last_activity_at=time.time() - 9999)

    roster = {
        a["name"]: a
        for a in tc.get("/v1/projects/mission-control").json()["agents"]
    }
    z = roster["Zombie"]
    assert z["working"] is False
    assert z["stale"] is True
    # Stale activity must not be surfaced as if it were live.
    assert z["current_activity"] == ""
