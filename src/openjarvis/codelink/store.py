"""CodeLinkStore — append-only SQLite store for FileEvents and CodeChangeLinks.

Soft-links to ``ProjectStore`` tasks/projects by id (own DB, no cross-DB FK).
Fills blank correlation ids from the active ``WorkContext``. Follows the
patterns of ``eventlog/store.py`` and ``approvals_center/store.py``.
"""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from openjarvis.codelink.context import WorkContext

_CREATE = """\
CREATE TABLE IF NOT EXISTS file_events (
    id           TEXT PRIMARY KEY,
    path         TEXT NOT NULL,
    change_type  TEXT NOT NULL,
    project_id   TEXT,
    task_id      TEXT,
    agent_id     TEXT,
    source       TEXT NOT NULL DEFAULT 'tool',
    at           REAL NOT NULL,
    old_path     TEXT,
    size         INTEGER
);
CREATE INDEX IF NOT EXISTS idx_fe_path ON file_events(path);
CREATE INDEX IF NOT EXISTS idx_fe_project ON file_events(project_id);
CREATE INDEX IF NOT EXISTS idx_fe_task ON file_events(task_id);
CREATE TABLE IF NOT EXISTS code_change_links (
    id            TEXT PRIMARY KEY,
    commit_sha    TEXT NOT NULL,
    repo_path     TEXT NOT NULL,
    project_id    TEXT,
    task_id       TEXT,
    agent_id      TEXT,
    message       TEXT NOT NULL DEFAULT '',
    files_changed TEXT NOT NULL DEFAULT '[]',
    insertions    INTEGER NOT NULL DEFAULT 0,
    deletions     INTEGER NOT NULL DEFAULT 0,
    committed_at  REAL,
    recorded_at   REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ccl_sha ON code_change_links(commit_sha);
CREATE INDEX IF NOT EXISTS idx_ccl_task ON code_change_links(task_id);
CREATE INDEX IF NOT EXISTS idx_ccl_project ON code_change_links(project_id);
"""


@dataclass(slots=True)
class FileEvent:
    id: str
    path: str
    change_type: str
    source: str
    at: float
    project_id: Optional[str] = None
    task_id: Optional[str] = None
    agent_id: Optional[str] = None
    old_path: Optional[str] = None
    size: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "path": self.path,
            "change_type": self.change_type,
            "source": self.source,
            "at": self.at,
            "project_id": self.project_id,
            "task_id": self.task_id,
            "agent_id": self.agent_id,
            "old_path": self.old_path,
            "size": self.size,
        }


@dataclass(slots=True)
class CodeChangeLink:
    id: str
    commit_sha: str
    repo_path: str
    recorded_at: float
    message: str = ""
    files_changed: List[str] = field(default_factory=list)
    insertions: int = 0
    deletions: int = 0
    project_id: Optional[str] = None
    task_id: Optional[str] = None
    agent_id: Optional[str] = None
    committed_at: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "commit_sha": self.commit_sha,
            "repo_path": self.repo_path,
            "recorded_at": self.recorded_at,
            "message": self.message,
            "files_changed": list(self.files_changed),
            "insertions": self.insertions,
            "deletions": self.deletions,
            "project_id": self.project_id,
            "task_id": self.task_id,
            "agent_id": self.agent_id,
            "committed_at": self.committed_at,
        }


def _resolve(value: str, key: str) -> Optional[str]:
    """Use explicit value if non-empty, else fall back to WorkContext."""
    v = str(value or "").strip()
    if v:
        return v
    return WorkContext.get().get(key)


class CodeLinkStore:
    """SQLite store for file events and code-change links."""

    def __init__(self, db_path: str = "") -> None:
        if not db_path:
            db_path = str(Path.home() / ".openjarvis" / "codelink.db")
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(_CREATE)
        self._conn.commit()

    def record_file_event(
        self,
        *,
        path: str,
        change_type: str,
        project_id: str = "",
        task_id: str = "",
        agent_id: str = "",
        source: str = "tool",
        old_path: Optional[str] = None,
        size: Optional[int] = None,
        now: Optional[float] = None,
    ) -> FileEvent:
        path = str(path or "").strip()
        if not path:
            raise ValueError("path is required")
        ts = now if now is not None else time.time()
        fe = FileEvent(
            id=uuid.uuid4().hex[:12],
            path=path,
            change_type=str(change_type or "modified"),
            source=str(source or "tool"),
            at=ts,
            project_id=_resolve(project_id, "project_id"),
            task_id=_resolve(task_id, "task_id"),
            agent_id=_resolve(agent_id, "agent_id"),
            old_path=old_path,
            size=size,
        )
        self._conn.execute(
            "INSERT INTO file_events"
            " (id, path, change_type, project_id, task_id, agent_id, source,"
            " at, old_path, size)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                fe.id,
                fe.path,
                fe.change_type,
                fe.project_id,
                fe.task_id,
                fe.agent_id,
                fe.source,
                fe.at,
                fe.old_path,
                fe.size,
            ),
        )
        self._conn.commit()
        return fe

    def _fe_row(self, row: sqlite3.Row) -> FileEvent:
        return FileEvent(
            id=row["id"],
            path=row["path"],
            change_type=row["change_type"],
            source=row["source"],
            at=row["at"],
            project_id=row["project_id"],
            task_id=row["task_id"],
            agent_id=row["agent_id"],
            old_path=row["old_path"],
            size=row["size"],
        )

    def file_events(
        self,
        *,
        path: Optional[str] = None,
        project_id: Optional[str] = None,
        task_id: Optional[str] = None,
        limit: int = 100,
    ) -> List[FileEvent]:
        clauses: List[str] = []
        params: List[Any] = []
        for col, val in (
            ("path", path),
            ("project_id", project_id),
            ("task_id", task_id),
        ):
            if val is not None:
                clauses.append(f"{col} = ?")
                params.append(val)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        params.append(limit)
        rows = self._conn.execute(
            f"SELECT * FROM file_events{where} ORDER BY at DESC, id DESC LIMIT ?",
            params,
        ).fetchall()
        return [self._fe_row(r) for r in rows]

    def events_for_path(self, path: str) -> List[FileEvent]:
        return self.file_events(path=path)

    def record_commit(
        self,
        *,
        commit_sha: str,
        repo_path: str,
        project_id: str = "",
        task_id: str = "",
        agent_id: str = "",
        message: str = "",
        files_changed: Optional[List[str]] = None,
        insertions: int = 0,
        deletions: int = 0,
        committed_at: Optional[float] = None,
        now: Optional[float] = None,
    ) -> CodeChangeLink:
        commit_sha = str(commit_sha or "").strip()
        if not commit_sha:
            raise ValueError("commit_sha is required")
        ts = now if now is not None else time.time()
        link = CodeChangeLink(
            id=uuid.uuid4().hex[:12],
            commit_sha=commit_sha,
            repo_path=str(repo_path or ""),
            recorded_at=ts,
            message=str(message or ""),
            files_changed=list(files_changed or []),
            insertions=int(insertions),
            deletions=int(deletions),
            project_id=_resolve(project_id, "project_id"),
            task_id=_resolve(task_id, "task_id"),
            agent_id=_resolve(agent_id, "agent_id"),
            committed_at=committed_at,
        )
        self._conn.execute(
            "INSERT INTO code_change_links"
            " (id, commit_sha, repo_path, project_id, task_id, agent_id,"
            " message, files_changed, insertions, deletions, committed_at,"
            " recorded_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                link.id,
                link.commit_sha,
                link.repo_path,
                link.project_id,
                link.task_id,
                link.agent_id,
                link.message,
                json.dumps(link.files_changed),
                link.insertions,
                link.deletions,
                link.committed_at,
                link.recorded_at,
            ),
        )
        self._conn.commit()
        return link

    def _ccl_row(self, row: sqlite3.Row) -> CodeChangeLink:
        return CodeChangeLink(
            id=row["id"],
            commit_sha=row["commit_sha"],
            repo_path=row["repo_path"],
            recorded_at=row["recorded_at"],
            message=row["message"],
            files_changed=json.loads(row["files_changed"])
            if row["files_changed"]
            else [],
            insertions=row["insertions"],
            deletions=row["deletions"],
            project_id=row["project_id"],
            task_id=row["task_id"],
            agent_id=row["agent_id"],
            committed_at=row["committed_at"],
        )

    def commits(
        self,
        *,
        commit_sha: Optional[str] = None,
        task_id: Optional[str] = None,
        project_id: Optional[str] = None,
        limit: int = 100,
    ) -> List[CodeChangeLink]:
        clauses: List[str] = []
        params: List[Any] = []
        for col, val in (
            ("commit_sha", commit_sha),
            ("task_id", task_id),
            ("project_id", project_id),
        ):
            if val is not None:
                clauses.append(f"{col} = ?")
                params.append(val)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        params.append(limit)
        rows = self._conn.execute(
            f"SELECT * FROM code_change_links{where}"
            f" ORDER BY recorded_at DESC, id DESC LIMIT ?",
            params,
        ).fetchall()
        return [self._ccl_row(r) for r in rows]

    def events_for_task(self, task_id: str) -> Dict[str, List[Any]]:
        return {
            "file_events": self.file_events(task_id=task_id),
            "commits": self.commits(task_id=task_id),
        }

    def close(self) -> None:
        self._conn.close()
