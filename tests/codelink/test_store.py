from __future__ import annotations

from openjarvis.codelink.context import WorkContext
from openjarvis.codelink.store import (
    CodeChangeLink,
    CodeLinkStore,
    FileEvent,
)


def _store(tmp_path):
    return CodeLinkStore(db_path=str(tmp_path / "cl.db"))


def test_record_file_event_explicit(tmp_path):
    WorkContext.clear()
    store = _store(tmp_path)
    fe = store.record_file_event(
        path="src/app.py",
        change_type="modified",
        project_id="p1",
        task_id="t1",
        agent_id="a1",
        source="tool",
        now=1000.0,
    )
    assert isinstance(fe, FileEvent)
    assert fe.path == "src/app.py"
    assert fe.task_id == "t1"
    assert fe.source == "tool"
    assert fe.at == 1000.0
    rows = store.file_events(task_id="t1")
    assert len(rows) == 1
    assert rows[0].path == "src/app.py"
    store.close()


def test_file_event_stamps_from_work_context(tmp_path):
    WorkContext.clear()
    store = _store(tmp_path)
    WorkContext.set(task_id="ctx-task", agent_id="ctx-agent", project_id="ctx-proj")
    fe = store.record_file_event(path="x.py", change_type="created", now=1.0)
    assert fe.task_id == "ctx-task"
    assert fe.agent_id == "ctx-agent"
    assert fe.project_id == "ctx-proj"
    fe2 = store.record_file_event(
        path="y.py", change_type="created", task_id="explicit", now=2.0
    )
    assert fe2.task_id == "explicit"
    assert fe2.agent_id == "ctx-agent"
    WorkContext.clear()
    store.close()


def test_moved_event_keeps_old_path(tmp_path):
    WorkContext.clear()
    store = _store(tmp_path)
    fe = store.record_file_event(
        path="new.py", change_type="moved", old_path="old.py", now=1.0
    )
    assert fe.change_type == "moved"
    assert fe.old_path == "old.py"
    assert store.events_for_path("new.py")[0].old_path == "old.py"
    store.close()


def test_record_commit_and_query(tmp_path):
    WorkContext.clear()
    store = _store(tmp_path)
    link = store.record_commit(
        commit_sha="abc123",
        repo_path="/repo",
        task_id="t1",
        message="fix bug",
        files_changed=["a.py", "b.py"],
        insertions=10,
        deletions=2,
        committed_at=500.0,
        now=1000.0,
    )
    assert isinstance(link, CodeChangeLink)
    assert link.commit_sha == "abc123"
    assert link.files_changed == ["a.py", "b.py"]
    assert link.insertions == 10
    got = store.commits(commit_sha="abc123")
    assert len(got) == 1
    assert got[0].files_changed == ["a.py", "b.py"]
    store.close()


def test_events_for_task_combines_both(tmp_path):
    WorkContext.clear()
    store = _store(tmp_path)
    store.record_file_event(path="a.py", change_type="modified", task_id="t1", now=1.0)
    store.record_commit(commit_sha="s1", repo_path="/r", task_id="t1", now=2.0)
    combined = store.events_for_task("t1")
    assert len(combined["file_events"]) == 1
    assert len(combined["commits"]) == 1
    store.close()


def test_record_file_event_requires_path(tmp_path):
    import pytest

    WorkContext.clear()
    store = _store(tmp_path)
    with pytest.raises(ValueError):
        store.record_file_event(path="  ", change_type="modified")
    store.close()
