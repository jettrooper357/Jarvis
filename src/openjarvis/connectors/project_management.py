"""Project management connector — exposes project/task/note data to agents.

This is the canonical bridge between the project-management store and the
OpenJarvis knowledge pipeline: each project is normalized into a single
``Document`` (project metadata + nested task tree + notes) so agents can
answer questions like "what's at risk in Project X" via knowledge search.

Local-first MVP: the source of truth is the SQLite ProjectStore. An
optional JSON config file can point at extra local project folders
(.json/.md/.yaml) to ingest alongside the store.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Iterator, Optional

from openjarvis.connectors._stubs import BaseConnector, Document, SyncStatus
from openjarvis.core.config import DEFAULT_CONFIG_DIR
from openjarvis.core.registry import ConnectorRegistry

_DEFAULT_CONFIG_PATH = str(
    DEFAULT_CONFIG_DIR / "connectors" / "project_management.json"
)


@ConnectorRegistry.register("project_management")
class ProjectManagementConnector(BaseConnector):
    """Feed projects, tasks, subtasks and notes into the knowledge graph."""

    connector_id = "project_management"
    display_name = "Project Management"
    auth_type = "local"
    config_template = (
        "{\n"
        '  "extra_project_dirs": ["~/.openjarvis/projects"]\n'
        "}\n"
    )

    def __init__(self, *, config_path: str = _DEFAULT_CONFIG_PATH) -> None:
        self._config_path = Path(config_path)
        self._status = SyncStatus()

    # -- helpers ---------------------------------------------------------

    def _store(self):
        from openjarvis.projects.store import ProjectStore

        return ProjectStore()

    def _extra_dirs(self) -> list[Path]:
        if not self._config_path.exists():
            return []
        try:
            data = json.loads(self._config_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        dirs = data.get("extra_project_dirs") or []
        out: list[Path] = []
        for d in dirs:
            if isinstance(d, str) and d.strip():
                out.append(Path(d).expanduser())
        return out

    # -- BaseConnector ---------------------------------------------------

    def is_connected(self) -> bool:
        # The project store always exists once any project is created; the
        # connector is "connected" whenever there is data or a config file.
        try:
            store = self._store()
            try:
                if store.list_projects():
                    return True
            finally:
                store.close()
        except Exception:
            pass
        return self._config_path.exists()

    def disconnect(self) -> None:
        if self._config_path.exists():
            self._config_path.unlink()

    def sync(
        self, *, since: Optional[datetime] = None, cursor: Optional[str] = None
    ) -> Iterator[Document]:
        self._status.state = "syncing"
        self._status.error = None
        self._status.items_synced = 0

        store = self._store()
        try:
            docs = store.export_documents()
        finally:
            store.close()

        self._status.items_total = len(docs)
        for d in docs:
            ts = datetime.now()
            yield Document(
                doc_id=d["doc_id"],
                source="project_management",
                doc_type="project",
                content=d["content"],
                title=d["title"],
                timestamp=ts,
                metadata={"project_id": d["project_id"]},
            )
            self._status.items_synced += 1

        # Optional: ingest extra local project files as raw documents.
        for root in self._extra_dirs():
            if not root.exists():
                continue
            for path in sorted(root.rglob("*")):
                if path.suffix.lower() not in (".json", ".md", ".yaml", ".yml"):
                    continue
                try:
                    text = path.read_text(encoding="utf-8")
                except OSError:
                    continue
                yield Document(
                    doc_id=f"projectfile-{path.name}",
                    source="project_management",
                    doc_type="project_file",
                    content=text[:20000],
                    title=path.name,
                    timestamp=datetime.now(),
                    url=str(path),
                )
                self._status.items_synced += 1

        self._status.state = "idle"
        self._status.last_sync = datetime.now()

    def sync_status(self) -> SyncStatus:
        return self._status


__all__ = ["ProjectManagementConnector"]
