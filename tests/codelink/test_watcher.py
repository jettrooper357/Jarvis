from __future__ import annotations

from openjarvis.codelink.context import WorkContext
from openjarvis.codelink.store import CodeLinkStore
from openjarvis.codelink.watcher import (
    _FileEventHandler,
    start_watchers,
    watchdog_available,
)


def _store(tmp_path):
    return CodeLinkStore(db_path=str(tmp_path / "cl.db"))


def test_handler_records_created_modified_deleted(tmp_path):
    WorkContext.clear()
    store = _store(tmp_path)
    handler = _FileEventHandler(store, project_id="p1")
    handler.handle("created", "src/a.py", is_directory=False)
    handler.handle("modified", "src/a.py", is_directory=False)
    handler.handle("deleted", "src/a.py", is_directory=False)
    events = store.file_events(path="src/a.py")
    types = sorted(e.change_type for e in events)
    assert types == ["created", "deleted", "modified"]
    assert all(e.source == "watcher" for e in events)
    assert all(e.project_id == "p1" for e in events)
    store.close()


def test_handler_ignores_noise_and_dirs(tmp_path):
    WorkContext.clear()
    store = _store(tmp_path)
    handler = _FileEventHandler(store, project_id="p1")
    handler.handle("modified", "src/.git/HEAD", is_directory=False)
    handler.handle("modified", "src/__pycache__/x.pyc", is_directory=False)
    handler.handle("created", "build/foo.pyc", is_directory=False)
    handler.handle("modified", "src/", is_directory=True)
    assert store.file_events() == []
    store.close()


def test_handler_moved_keeps_old_path(tmp_path):
    WorkContext.clear()
    store = _store(tmp_path)
    handler = _FileEventHandler(store, project_id="p1")
    handler.handle("moved", "dst.py", is_directory=False, old_path="src.py")
    fe = store.file_events(path="dst.py")[0]
    assert fe.change_type == "moved"
    assert fe.old_path == "src.py"
    store.close()


def test_start_watchers_disabled_is_noop(tmp_path):
    store = _store(tmp_path)
    mgr = start_watchers(
        store,
        [{"id": "p1", "working_folder": str(tmp_path)}],
        enabled=False,
    )
    assert mgr.active == 0
    mgr.stop_all()
    store.close()


def test_watchdog_available_is_bool():
    assert isinstance(watchdog_available(), bool)
