"""Optional filesystem watcher for project working folders.

Wraps ``watchdog`` when available; degrades to a no-op manager when the
dependency is missing or watching is disabled. The FS-event→record mapping
lives in ``_FileEventHandler.handle`` so it is testable without ``watchdog``.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional

from openjarvis.codelink.store import CodeLinkStore

logger = logging.getLogger(__name__)

_IGNORE_DIRS = (".git", "__pycache__", "node_modules", ".venv", "build", "dist")
_IGNORE_SUFFIXES = (".pyc", ".pyo", ".swp", "~")


def watchdog_available() -> bool:
    """Return True if the optional ``watchdog`` dependency can be imported."""
    try:
        import watchdog  # noqa: F401
        import watchdog.observers  # noqa: F401
    except Exception:
        return False
    return True


def _ignored(path: str) -> bool:
    parts = path.replace("\\", "/").split("/")
    if any(seg in _IGNORE_DIRS for seg in parts):
        return True
    return path.endswith(_IGNORE_SUFFIXES)


class _FileEventHandler:
    """Maps filesystem events to ``CodeLinkStore.record_file_event`` calls."""

    def __init__(self, store: CodeLinkStore, *, project_id: str) -> None:
        self._store = store
        self._project_id = project_id

    def handle(
        self,
        change_type: str,
        path: str,
        *,
        is_directory: bool,
        old_path: Optional[str] = None,
    ) -> None:
        if is_directory or _ignored(path):
            return
        if old_path is not None and _ignored(old_path):
            return
        self._store.record_file_event(
            path=path,
            change_type=change_type,
            project_id=self._project_id,
            source="watcher",
            old_path=old_path,
        )


class ProjectFolderWatcher:
    """Watches one project working folder via a watchdog Observer."""

    def __init__(
        self,
        store: CodeLinkStore,
        *,
        project_id: str,
        working_folder: str,
    ) -> None:
        self._handler = _FileEventHandler(store, project_id=project_id)
        self._working_folder = working_folder
        self._observer: Any = None

    def start(self) -> bool:
        """Start observing. Returns True if the observer started."""
        try:
            from watchdog.events import FileSystemEventHandler
            from watchdog.observers import Observer
        except Exception:
            return False
        if not os.path.isdir(self._working_folder):
            return False

        handler = self._handler

        class _Adapter(FileSystemEventHandler):
            def on_created(self, event: Any) -> None:
                handler.handle(
                    "created", event.src_path, is_directory=event.is_directory
                )

            def on_modified(self, event: Any) -> None:
                handler.handle(
                    "modified", event.src_path, is_directory=event.is_directory
                )

            def on_deleted(self, event: Any) -> None:
                handler.handle(
                    "deleted", event.src_path, is_directory=event.is_directory
                )

            def on_moved(self, event: Any) -> None:
                handler.handle(
                    "moved",
                    getattr(event, "dest_path", event.src_path),
                    is_directory=event.is_directory,
                    old_path=event.src_path,
                )

        self._observer = Observer()
        self._observer.schedule(_Adapter(), self._working_folder, recursive=True)
        self._observer.start()
        return True

    def stop(self) -> None:
        if self._observer is not None:
            try:
                self._observer.stop()
                self._observer.join(timeout=2.0)
            except Exception:
                pass
            self._observer = None


class WatcherManager:
    """Holds the running watchers and the active count."""

    def __init__(self, watchers: List[ProjectFolderWatcher]) -> None:
        self._watchers = watchers

    @property
    def active(self) -> int:
        return len(self._watchers)

    def stop_all(self) -> None:
        for w in self._watchers:
            w.stop()
        self._watchers = []


def start_watchers(
    store: CodeLinkStore,
    projects: List[Dict[str, Any]],
    *,
    enabled: bool,
) -> WatcherManager:
    """Start one watcher per project with a working folder.

    Returns a no-op manager (``active == 0``) when disabled or when
    ``watchdog`` is unavailable — never raises.
    """
    if not enabled:
        return WatcherManager([])
    if not watchdog_available():
        logger.info("codelink watcher: watchdog not installed; watching disabled")
        return WatcherManager([])
    started: List[ProjectFolderWatcher] = []
    for proj in projects:
        folder = str(proj.get("working_folder") or "").strip()
        if not folder:
            continue
        watcher = ProjectFolderWatcher(
            store, project_id=str(proj.get("id") or ""), working_folder=folder
        )
        try:
            if watcher.start():
                started.append(watcher)
        except Exception:
            logger.exception("codelink watcher failed for %s", folder)
    return WatcherManager(started)
