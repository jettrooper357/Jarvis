from __future__ import annotations

from datetime import datetime, timedelta

from openjarvis.projects.store import ProjectStore
from openjarvis.tools.project_tools import (
    ProjectAddCategoryTool,
    ProjectAddMilestoneTool,
    ProjectAddNoteTool,
    ProjectCreateTaskTool,
    ProjectCreateTool,
    ProjectDeleteCategoryTool,
    ProjectDeleteMilestoneTool,
    ProjectDeleteTaskTool,
    ProjectListTool,
    ProjectRenameCategoryTool,
    ProjectUpdateMilestoneTool,
    ProjectUpdateTaskTool,
)


def test_project_create_tool_creates_project(monkeypatch, tmp_path):
    store = ProjectStore(tmp_path / "projects.db")
    monkeypatch.setattr("openjarvis.tools.project_tools._project_store", lambda: store)

    result = ProjectCreateTool().execute(name="Iron Saints Music", status="Active")

    assert result.success is True
    assert "Created project" in result.content
    assert result.metadata["project"]["name"] == "Iron Saints Music"
    created = store.get_project(result.metadata["project_id"])
    assert created["name"] == "Iron Saints Music"


def test_project_create_task_returns_project_task_id(monkeypatch, tmp_path):
    store = ProjectStore(tmp_path / "projects.db")
    project = store.create_project(name="Iron Saints Music")
    monkeypatch.setattr("openjarvis.tools.project_tools._project_store", lambda: store)

    result = ProjectCreateTaskTool().execute(
        project_id=project["id"],
        title="add a task to release a new song called Raise One for the Old Guard",
        status="Backlog",
    )

    assert result.success is True
    assert result.metadata["project_id"] == project["id"]
    assert result.metadata["project_task_id"]
    created_task = store.get_task(result.metadata["project_task_id"])
    assert created_task["title"] == "Raise One for the Old Guard"
    today = datetime.now().date()
    assert created_task["start_date"] == today.isoformat()
    assert created_task["due_date"] == (today + timedelta(days=1)).isoformat()


def test_project_create_task_strips_trailing_project_phrase(monkeypatch, tmp_path):
    store = ProjectStore(tmp_path / "projects.db")
    project = store.create_project(name="Iron Saints Music")
    monkeypatch.setattr("openjarvis.tools.project_tools._project_store", lambda: store)

    result = ProjectCreateTaskTool().execute(
        project_id=project["id"],
        title="Raise One for the Old Guard to the Iron Saints Project",
    )

    assert result.success is True
    created_task = store.get_task(result.metadata["project_task_id"])
    assert created_task["title"] == "Raise One for the Old Guard"


def test_project_list_tool_filters_projects(monkeypatch, tmp_path):
    store = ProjectStore(tmp_path / "projects.db")
    store.create_project(name="Iron Saints Music")
    store.create_project(name="Other Project")
    monkeypatch.setattr("openjarvis.tools.project_tools._project_store", lambda: store)

    result = ProjectListTool().execute(query="saints")

    assert result.success is True
    assert "Iron Saints Music" in result.content
    assert "Other Project" not in result.content


def _store(monkeypatch, tmp_path):
    store = ProjectStore(tmp_path / "projects.db")
    monkeypatch.setattr(
        "openjarvis.tools.project_tools._project_store", lambda: store
    )
    return store


def test_update_and_delete_task_tools(monkeypatch, tmp_path):
    store = _store(monkeypatch, tmp_path)
    project = store.create_project(name="Apollo")
    task = store.create_task(project["id"], title="Build", category="Backend")

    upd = ProjectUpdateTaskTool().execute(
        task_id=task["id"], status="Done", percent_complete=100
    )
    assert upd.success is True
    refreshed = store.get_task(task["id"])
    assert refreshed["status"] == "Done"
    assert refreshed["percent_complete"] == 100
    assert refreshed["category"] == "Backend"

    missing = ProjectUpdateTaskTool().execute(task_id="nope", status="Done")
    assert missing.success is False

    deleted = ProjectDeleteTaskTool().execute(task_id=task["id"])
    assert deleted.success is True
    assert store.get_task(task["id"]) is None


def test_add_note_tool(monkeypatch, tmp_path):
    store = _store(monkeypatch, tmp_path)
    project = store.create_project(name="Apollo")
    task = store.create_task(project["id"], title="Build")

    result = ProjectAddNoteTool().execute(
        task_id=task["id"], content="Made progress today", author="Atlas"
    )
    assert result.success is True
    notes = store.list_notes(task["id"])
    assert len(notes) == 1 and notes[0]["content"] == "Made progress today"

    bad = ProjectAddNoteTool().execute(task_id="nope", content="x")
    assert bad.success is False


def test_milestone_tools_lifecycle(monkeypatch, tmp_path):
    store = _store(monkeypatch, tmp_path)
    project = store.create_project(name="Apollo")

    added = ProjectAddMilestoneTool().execute(
        project_id=project["id"], name="MVP", date="Jun 13"
    )
    assert added.success is True
    mid = added.metadata["milestone"]["id"]

    upd = ProjectUpdateMilestoneTool().execute(
        project_id=project["id"], milestone_id=mid, done=True
    )
    assert upd.success is True
    assert store.list_milestones(project["id"])[0]["done"] is True

    dele = ProjectDeleteMilestoneTool().execute(
        project_id=project["id"], milestone_id=mid
    )
    assert dele.success is True
    assert store.list_milestones(project["id"]) == []


def test_category_tools_lifecycle(monkeypatch, tmp_path):
    store = _store(monkeypatch, tmp_path)
    project = store.create_project(name="Apollo")
    task = store.create_task(
        project["id"], title="API layer", category="Backend"
    )

    # Empty category persists before any task uses it.
    add = ProjectAddCategoryTool().execute(
        project_id=project["id"], name="Frontend"
    )
    assert add.success is True
    assert "Frontend" in add.metadata["categories"]
    assert "Backend" in add.metadata["categories"]

    ren = ProjectRenameCategoryTool().execute(
        project_id=project["id"], old_name="Backend", new_name="Core"
    )
    assert ren.success is True
    assert store.get_task(task["id"])["category"] == "Core"

    dele = ProjectDeleteCategoryTool().execute(
        project_id=project["id"], name="Core"
    )
    assert dele.success is True
    assert store.get_task(task["id"])["category"] == ""
    assert "Core" not in store.list_categories(project["id"])


def test_project_timeline_skill_grants_full_toolset():
    from openjarvis.agents.capabilities import (
        _collect_skill_tool_dependencies,
        _skill_paths,
    )
    from openjarvis.skills.manager import SkillManager

    manager = SkillManager(None)
    manager.discover(paths=_skill_paths())
    collected: set[str] = set()
    _collect_skill_tool_dependencies(
        "project-timeline", manager, collected, set()
    )
    for name in (
        "project_list",
        "project_create_task",
        "project_update_task",
        "project_delete_task",
        "project_add_note",
        "project_add_milestone",
        "project_update_milestone",
        "project_delete_milestone",
        "project_add_category",
        "project_rename_category",
        "project_delete_category",
    ):
        assert name in collected


def test_chief_gets_full_project_toolset():
    from openjarvis.agents.capabilities import effective_agent_tool_names

    tools = effective_agent_tool_names(
        {"id": "c", "name": "Chief", "org_role": "Chief Orchestrator",
         "agent_type": "monitor_operative", "config": {}}
    )
    for name in (
        "project_update_task",
        "project_delete_task",
        "project_add_note",
        "project_add_milestone",
        "project_update_milestone",
        "project_delete_milestone",
        "project_add_category",
        "project_rename_category",
        "project_delete_category",
    ):
        assert name in tools
