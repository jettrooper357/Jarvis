"""SQLite store for projects, nested tasks/subtasks and notes.

Schema is intentionally close to the project-management plan's data model:

* projects   — portfolio entries with owner/team/dates/status/progress
* tasks      — nested via ``parent_task_id`` (self-referential), with
               assignee, status, priority, dates, percent_complete
* notes      — attached to a task, with an optional AI summary

Progress rolls up: a project's ``progress`` is derived from the average
``percent_complete`` of its top-level tasks unless explicitly set.
"""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from openjarvis.core.config import DEFAULT_CONFIG_DIR

_SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    owner       TEXT NOT NULL DEFAULT '',
    team        TEXT NOT NULL DEFAULT '[]',
    start_date  TEXT,
    target_date TEXT,
    status      TEXT NOT NULL DEFAULT 'Planning',
    progress    INTEGER NOT NULL DEFAULT 0,
    tags        TEXT NOT NULL DEFAULT '[]',
    milestones  TEXT NOT NULL DEFAULT '[]',
    created_at  REAL NOT NULL,
    updated_at  REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS tasks (
    id              TEXT PRIMARY KEY,
    project_id      TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    parent_task_id  TEXT REFERENCES tasks(id) ON DELETE CASCADE,
    title           TEXT NOT NULL,
    description     TEXT NOT NULL DEFAULT '',
    type            TEXT NOT NULL DEFAULT 'Feature',
    status          TEXT NOT NULL DEFAULT 'Backlog',
    assigned_to     TEXT NOT NULL DEFAULT '',
    owner           TEXT NOT NULL DEFAULT '',
    priority        TEXT NOT NULL DEFAULT 'Medium',
    start_date      TEXT,
    due_date        TEXT,
    percent_complete INTEGER NOT NULL DEFAULT 0,
    estimate_hours  REAL,
    dependencies    TEXT NOT NULL DEFAULT '[]',
    sort_order      INTEGER NOT NULL DEFAULT 0,
    created_at      REAL NOT NULL,
    updated_at      REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS notes (
    id          TEXT PRIMARY KEY,
    task_id     TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    author      TEXT NOT NULL DEFAULT '',
    content     TEXT NOT NULL DEFAULT '',
    type        TEXT NOT NULL DEFAULT 'Comment',
    ai_summary  TEXT,
    created_at  REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_tasks_project ON tasks(project_id);
CREATE INDEX IF NOT EXISTS idx_tasks_parent ON tasks(parent_task_id);
CREATE INDEX IF NOT EXISTS idx_notes_task ON notes(task_id);
"""

_JSON_PROJECT_FIELDS = ("team", "tags", "milestones")
_JSON_TASK_FIELDS = ("dependencies",)


def _now() -> float:
    return time.time()


def _gen_id() -> str:
    return uuid.uuid4().hex[:12]


def default_db_path() -> Path:
    return DEFAULT_CONFIG_DIR / "projects.db"


class ProjectStore:
    """Thread-safe-enough SQLite wrapper for projects/tasks/notes."""

    def __init__(self, db_path: Optional[str | Path] = None) -> None:
        self._path = Path(db_path) if db_path else default_db_path()
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    # -- serialization helpers -------------------------------------------

    @staticmethod
    def _row_to_project(row: sqlite3.Row) -> Dict[str, Any]:
        d = dict(row)
        for f in _JSON_PROJECT_FIELDS:
            try:
                d[f] = json.loads(d.get(f) or "[]")
            except (TypeError, json.JSONDecodeError):
                d[f] = []
        return d

    @staticmethod
    def _row_to_task(row: sqlite3.Row) -> Dict[str, Any]:
        d = dict(row)
        for f in _JSON_TASK_FIELDS:
            try:
                d[f] = json.loads(d.get(f) or "[]")
            except (TypeError, json.JSONDecodeError):
                d[f] = []
        return d

    # -- projects --------------------------------------------------------

    def list_projects(self) -> List[Dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM projects ORDER BY created_at DESC"
        ).fetchall()
        out = []
        for r in rows:
            p = self._row_to_project(r)
            p["progress"] = self._rollup_progress(p["id"], p.get("progress", 0))
            out.append(p)
        return out

    def get_project(self, project_id: str) -> Optional[Dict[str, Any]]:
        r = self._conn.execute(
            "SELECT * FROM projects WHERE id = ?", (project_id,)
        ).fetchone()
        if not r:
            return None
        p = self._row_to_project(r)
        p["progress"] = self._rollup_progress(project_id, p.get("progress", 0))
        return p

    def create_project(self, **fields: Any) -> Dict[str, Any]:
        pid = _gen_id()
        now = _now()
        self._conn.execute(
            "INSERT INTO projects (id, name, description, owner, team, "
            "start_date, target_date, status, progress, tags, milestones, "
            "created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                pid,
                str(fields.get("name") or "Untitled Project"),
                str(fields.get("description") or ""),
                str(fields.get("owner") or ""),
                json.dumps(fields.get("team") or []),
                fields.get("start_date"),
                fields.get("target_date"),
                str(fields.get("status") or "Planning"),
                int(fields.get("progress") or 0),
                json.dumps(fields.get("tags") or []),
                json.dumps(fields.get("milestones") or []),
                now,
                now,
            ),
        )
        self._conn.commit()
        return self.get_project(pid)  # type: ignore[return-value]

    def update_project(self, project_id: str, **fields: Any) -> Dict[str, Any]:
        if not self.get_project(project_id):
            raise KeyError(project_id)
        cols, params = [], []
        for key, val in fields.items():
            if key in _JSON_PROJECT_FIELDS:
                cols.append(f"{key} = ?")
                params.append(json.dumps(val))
            elif key in (
                "name",
                "description",
                "owner",
                "start_date",
                "target_date",
                "status",
                "progress",
            ):
                cols.append(f"{key} = ?")
                params.append(val)
        if cols:
            cols.append("updated_at = ?")
            params.append(_now())
            params.append(project_id)
            self._conn.execute(
                f"UPDATE projects SET {', '.join(cols)} WHERE id = ?", params
            )
            self._conn.commit()
        return self.get_project(project_id)  # type: ignore[return-value]

    def delete_project(self, project_id: str) -> None:
        self._conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))
        self._conn.commit()

    # -- tasks -----------------------------------------------------------

    def list_tasks(self, project_id: str) -> List[Dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM tasks WHERE project_id = ? "
            "ORDER BY sort_order, created_at",
            (project_id,),
        ).fetchall()
        return [self._row_to_task(r) for r in rows]

    def get_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        r = self._conn.execute(
            "SELECT * FROM tasks WHERE id = ?", (task_id,)
        ).fetchone()
        return self._row_to_task(r) if r else None

    def create_task(self, project_id: str, **fields: Any) -> Dict[str, Any]:
        if not self.get_project(project_id):
            raise KeyError(project_id)
        tid = _gen_id()
        now = _now()
        self._conn.execute(
            "INSERT INTO tasks (id, project_id, parent_task_id, title, "
            "description, type, status, assigned_to, owner, priority, "
            "start_date, due_date, percent_complete, estimate_hours, "
            "dependencies, sort_order, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                tid,
                project_id,
                fields.get("parent_task_id"),
                str(fields.get("title") or "Untitled Task"),
                str(fields.get("description") or ""),
                str(fields.get("type") or "Feature"),
                str(fields.get("status") or "Backlog"),
                str(fields.get("assigned_to") or ""),
                str(fields.get("owner") or ""),
                str(fields.get("priority") or "Medium"),
                fields.get("start_date"),
                fields.get("due_date"),
                int(fields.get("percent_complete") or 0),
                fields.get("estimate_hours"),
                json.dumps(fields.get("dependencies") or []),
                int(fields.get("sort_order") or 0),
                now,
                now,
            ),
        )
        self._conn.commit()
        return self.get_task(tid)  # type: ignore[return-value]

    def update_task(self, task_id: str, **fields: Any) -> Dict[str, Any]:
        if not self.get_task(task_id):
            raise KeyError(task_id)
        cols, params = [], []
        for key, val in fields.items():
            if key in _JSON_TASK_FIELDS:
                cols.append(f"{key} = ?")
                params.append(json.dumps(val))
            elif key in (
                "parent_task_id",
                "title",
                "description",
                "type",
                "status",
                "assigned_to",
                "owner",
                "priority",
                "start_date",
                "due_date",
                "percent_complete",
                "estimate_hours",
                "sort_order",
            ):
                cols.append(f"{key} = ?")
                params.append(val)
        if cols:
            cols.append("updated_at = ?")
            params.append(_now())
            params.append(task_id)
            self._conn.execute(
                f"UPDATE tasks SET {', '.join(cols)} WHERE id = ?", params
            )
            self._conn.commit()
        return self.get_task(task_id)  # type: ignore[return-value]

    def delete_task(self, task_id: str) -> None:
        self._conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
        self._conn.commit()

    # -- notes -----------------------------------------------------------

    def list_notes(self, task_id: str) -> List[Dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM notes WHERE task_id = ? ORDER BY created_at",
            (task_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def add_note(self, task_id: str, **fields: Any) -> Dict[str, Any]:
        if not self.get_task(task_id):
            raise KeyError(task_id)
        nid = _gen_id()
        self._conn.execute(
            "INSERT INTO notes (id, task_id, author, content, type, "
            "ai_summary, created_at) VALUES (?,?,?,?,?,?,?)",
            (
                nid,
                task_id,
                str(fields.get("author") or ""),
                str(fields.get("content") or ""),
                str(fields.get("type") or "Comment"),
                fields.get("ai_summary"),
                _now(),
            ),
        )
        self._conn.commit()
        r = self._conn.execute(
            "SELECT * FROM notes WHERE id = ?", (nid,)
        ).fetchone()
        return dict(r)

    def update_note(self, note_id: str, **fields: Any) -> Dict[str, Any]:
        cols, params = [], []
        for key in ("content", "type", "ai_summary", "author"):
            if key in fields:
                cols.append(f"{key} = ?")
                params.append(fields[key])
        if cols:
            params.append(note_id)
            self._conn.execute(
                f"UPDATE notes SET {', '.join(cols)} WHERE id = ?", params
            )
            self._conn.commit()
        r = self._conn.execute(
            "SELECT * FROM notes WHERE id = ?", (note_id,)
        ).fetchone()
        if not r:
            raise KeyError(note_id)
        return dict(r)

    def delete_note(self, note_id: str) -> None:
        self._conn.execute("DELETE FROM notes WHERE id = ?", (note_id,))
        self._conn.commit()

    # -- analytics -------------------------------------------------------

    def _rollup_progress(self, project_id: str, explicit: int) -> int:
        """Average percent_complete of top-level tasks (fallback to explicit)."""
        row = self._conn.execute(
            "SELECT AVG(percent_complete) AS avg FROM tasks "
            "WHERE project_id = ? AND parent_task_id IS NULL",
            (project_id,),
        ).fetchone()
        if row and row["avg"] is not None:
            return int(round(row["avg"]))
        return int(explicit or 0)

    def dashboard(self) -> Dict[str, Any]:
        """Portfolio KPIs for the dashboard widgets."""
        projects = self.list_projects()
        now = time.time()
        all_tasks = self._conn.execute("SELECT * FROM tasks").fetchall()
        tasks = [self._row_to_task(r) for r in all_tasks]

        def _is_overdue(t: Dict[str, Any]) -> bool:
            due = t.get("due_date")
            if not due or t.get("status") in ("Done", "Cancelled"):
                return False
            try:
                import datetime as _dt

                d = _dt.datetime.fromisoformat(str(due).replace("Z", "+00:00"))
                return d.timestamp() < now
            except (ValueError, TypeError):
                return False

        overdue = [t for t in tasks if _is_overdue(t)]
        blocked = [t for t in tasks if t.get("status") == "Blocked"]
        in_progress = [t for t in tasks if t.get("status") == "In Progress"]
        done = [t for t in tasks if t.get("status") == "Done"]
        active_projects = [
            p for p in projects if p.get("status") in ("Active", "Planning")
        ]
        at_risk = [
            p for p in projects if p.get("status") in ("At Risk", "Delayed")
        ]
        avg_completion = (
            int(round(sum(p.get("progress", 0) for p in projects) / len(projects)))
            if projects
            else 0
        )
        # Workload by assignee
        workload: Dict[str, int] = {}
        for t in tasks:
            if t.get("status") in ("Done", "Cancelled"):
                continue
            who = t.get("assigned_to") or "Unassigned"
            workload[who] = workload.get(who, 0) + 1

        return {
            "projects_total": len(projects),
            "projects_active": len(active_projects),
            "projects_at_risk": len(at_risk),
            "tasks_total": len(tasks),
            "tasks_in_progress": len(in_progress),
            "tasks_overdue": len(overdue),
            "tasks_blocked": len(blocked),
            "tasks_done": len(done),
            "avg_completion": avg_completion,
            "workload_by_assignee": workload,
            "at_risk_projects": [
                {"id": p["id"], "name": p["name"], "status": p["status"]}
                for p in at_risk
            ],
        }

    def export_documents(self) -> List[Dict[str, Any]]:
        """Flatten everything into text blobs for the connector / agents."""
        docs: List[Dict[str, Any]] = []
        for p in self.list_projects():
            tasks = self.list_tasks(p["id"])
            lines = [
                f"# Project: {p['name']}",
                p.get("description", ""),
                f"Status: {p.get('status')} · Progress: {p.get('progress')}%"
                f" · Owner: {p.get('owner') or 'unassigned'}",
                f"Dates: {p.get('start_date') or '?'} → "
                f"{p.get('target_date') or '?'}",
                "",
                "## Tasks",
            ]
            for t in tasks:
                indent = "  " if t.get("parent_task_id") else ""
                lines.append(
                    f"{indent}- [{t.get('status')}] {t.get('title')} "
                    f"({t.get('percent_complete')}%, "
                    f"priority {t.get('priority')}, "
                    f"assignee {t.get('assigned_to') or 'unassigned'}, "
                    f"due {t.get('due_date') or 'n/a'})"
                )
                for n in self.list_notes(t["id"]):
                    lines.append(
                        f"{indent}  note ({n.get('type')}): {n.get('content')}"
                    )
            docs.append(
                {
                    "doc_id": f"project-{p['id']}",
                    "title": p["name"],
                    "content": "\n".join(s for s in lines if s is not None),
                    "project_id": p["id"],
                    "updated_at": p.get("updated_at"),
                }
            )
        return docs

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "ProjectStore":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()
