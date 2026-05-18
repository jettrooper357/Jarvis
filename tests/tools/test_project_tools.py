from __future__ import annotations

from openjarvis.projects.store import ProjectStore
from openjarvis.tools.project_tools import (
    ProjectCreateTaskTool,
    ProjectCreateTool,
    ProjectListTool,
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
        title="Set up launch plan",
        status="Backlog",
    )

    assert result.success is True
    assert result.metadata["project_id"] == project["id"]
    assert result.metadata["project_task_id"]
    created_task = store.get_task(result.metadata["project_task_id"])
    assert created_task["title"] == "Set up launch plan"


def test_project_list_tool_filters_projects(monkeypatch, tmp_path):
    store = ProjectStore(tmp_path / "projects.db")
    store.create_project(name="Iron Saints Music")
    store.create_project(name="Other Project")
    monkeypatch.setattr("openjarvis.tools.project_tools._project_store", lambda: store)

    result = ProjectListTool().execute(query="saints")

    assert result.success is True
    assert "Iron Saints Music" in result.content
    assert "Other Project" not in result.content
