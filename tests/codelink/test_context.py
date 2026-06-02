from __future__ import annotations

from openjarvis.codelink.context import WorkContext, work_context


def test_set_get_clear():
    WorkContext.clear()
    assert WorkContext.get() == {
        "task_id": None,
        "agent_id": None,
        "project_id": None,
    }
    WorkContext.set(task_id="t1", agent_id="a1")
    assert WorkContext.get()["task_id"] == "t1"
    assert WorkContext.get()["agent_id"] == "a1"
    WorkContext.clear()
    assert WorkContext.get()["task_id"] is None


def test_context_manager_restores_prior():
    WorkContext.clear()
    WorkContext.set(task_id="outer")
    with work_context(task_id="inner", project_id="p1"):
        assert WorkContext.get()["task_id"] == "inner"
        assert WorkContext.get()["project_id"] == "p1"
    assert WorkContext.get()["task_id"] == "outer"
    assert WorkContext.get()["project_id"] is None
    WorkContext.clear()
