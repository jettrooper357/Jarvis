"""RollbackStore — append-only SQLite store for reversible autonomous actions.

Records each reversible action with an opaque ``undo_payload``; ``revert``
dispatches to the handler registry. Follows the patterns of
``eventlog/store.py`` and ``approvals_center/store.py``.
"""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from openjarvis.autonomy import handlers as _handlers

_CREATE = """\
CREATE TABLE IF NOT EXISTS reversible_actions (
    id            TEXT PRIMARY KEY,
    action_type   TEXT NOT NULL,
    summary       TEXT NOT NULL DEFAULT '',
    undo_payload  TEXT NOT NULL DEFAULT '{}',
    status        TEXT NOT NULL DEFAULT 'active',
    agent_id      TEXT,
    task_id       TEXT,
    created_at    REAL NOT NULL,
    reverted_at   REAL,
    revert_note   TEXT
);
CREATE INDEX IF NOT EXISTS idx_ra_type ON reversible_actions(action_type);
CREATE INDEX IF NOT EXISTS idx_ra_status ON reversible_actions(status);
CREATE INDEX IF NOT EXISTS idx_ra_agent ON reversible_actions(agent_id);
CREATE INDEX IF NOT EXISTS idx_ra_task ON reversible_actions(task_id);
CREATE TABLE IF NOT EXISTS reversible_action_events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    action_id   TEXT NOT NULL,
    from_status TEXT NOT NULL,
    to_status   TEXT NOT NULL,
    at          REAL NOT NULL,
    detail      TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_rae_action ON reversible_action_events(action_id);
"""


class RollbackError(ValueError):
    """Raised on invalid revert transitions, missing actions, or undo failure."""


@dataclass(slots=True)
class ReversibleAction:
    id: str
    action_type: str
    summary: str
    status: str
    created_at: float
    undo_payload: Dict[str, Any] = field(default_factory=dict)
    agent_id: Optional[str] = None
    task_id: Optional[str] = None
    reverted_at: Optional[float] = None
    revert_note: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "action_type": self.action_type,
            "summary": self.summary,
            "status": self.status,
            "created_at": self.created_at,
            "undo_payload": dict(self.undo_payload),
            "agent_id": self.agent_id,
            "task_id": self.task_id,
            "reverted_at": self.reverted_at,
            "revert_note": self.revert_note,
        }


class RollbackStore:
    """SQLite store for reversible actions + their revert trail."""

    def __init__(self, db_path: str = "") -> None:
        if not db_path:
            db_path = str(Path.home() / ".openjarvis" / "autonomy.db")
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(_CREATE)
        self._conn.commit()

    def _row(self, row: sqlite3.Row) -> ReversibleAction:
        return ReversibleAction(
            id=row["id"],
            action_type=row["action_type"],
            summary=row["summary"],
            status=row["status"],
            created_at=row["created_at"],
            undo_payload=json.loads(row["undo_payload"]) if row["undo_payload"] else {},
            agent_id=row["agent_id"],
            task_id=row["task_id"],
            reverted_at=row["reverted_at"],
            revert_note=row["revert_note"],
        )

    def _append_event(
        self,
        action_id: str,
        from_status: str,
        to_status: str,
        at: float,
        detail: str = "",
    ) -> None:
        self._conn.execute(
            "INSERT INTO reversible_action_events"
            " (action_id, from_status, to_status, at, detail)"
            " VALUES (?, ?, ?, ?, ?)",
            (action_id, from_status, to_status, at, detail),
        )

    def record(
        self,
        *,
        action_type: str,
        summary: str,
        undo_payload: Optional[Dict[str, Any]] = None,
        agent_id: str = "",
        task_id: str = "",
        reversible: bool = True,
        now: Optional[float] = None,
    ) -> ReversibleAction:
        action_type = str(action_type or "").strip()
        if not action_type:
            raise ValueError("action_type is required")
        ts = now if now is not None else time.time()
        status = (
            "active"
            if reversible and _handlers.has_handler(action_type)
            else "irreversible"
        )
        a = ReversibleAction(
            id=uuid.uuid4().hex[:12],
            action_type=action_type,
            summary=str(summary or ""),
            status=status,
            created_at=ts,
            undo_payload=dict(undo_payload or {}),
            agent_id=agent_id or None,
            task_id=task_id or None,
        )
        self._conn.execute(
            "INSERT INTO reversible_actions"
            " (id, action_type, summary, undo_payload, status, agent_id,"
            " task_id, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                a.id,
                a.action_type,
                a.summary,
                json.dumps(a.undo_payload),
                a.status,
                a.agent_id,
                a.task_id,
                a.created_at,
            ),
        )
        self._append_event(a.id, "", status, ts, "recorded")
        self._conn.commit()
        return a

    def get(self, action_id: str) -> Optional[ReversibleAction]:
        row = self._conn.execute(
            "SELECT * FROM reversible_actions WHERE id = ?", (action_id,)
        ).fetchone()
        return self._row(row) if row else None

    def list(
        self,
        *,
        status: Optional[str] = None,
        agent_id: Optional[str] = None,
        action_type: Optional[str] = None,
        limit: int = 100,
    ) -> List[ReversibleAction]:
        clauses: List[str] = []
        params: List[Any] = []
        for col, val in (
            ("status", status),
            ("agent_id", agent_id),
            ("action_type", action_type),
        ):
            if val is not None:
                clauses.append(f"{col} = ?")
                params.append(val)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        params.append(limit)
        rows = self._conn.execute(
            f"SELECT * FROM reversible_actions{where}"
            f" ORDER BY created_at DESC, id DESC LIMIT ?",
            params,
        ).fetchall()
        return [self._row(r) for r in rows]

    def history(self, action_id: str) -> List[Dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT from_status, to_status, at, detail"
            " FROM reversible_action_events WHERE action_id = ?"
            " ORDER BY id ASC",
            (action_id,),
        ).fetchall()
        return [
            {
                "from_status": r["from_status"],
                "to_status": r["to_status"],
                "at": r["at"],
                "detail": r["detail"],
            }
            for r in rows
        ]

    def revert(
        self, action_id: str, *, note: str = "", now: Optional[float] = None
    ) -> ReversibleAction:
        existing = self.get(action_id)
        if existing is None:
            raise RollbackError(f"Action not found: {action_id!r}")
        if existing.status == "reverted":
            raise RollbackError(f"Action {action_id!r} is already reverted.")
        ts = now if now is not None else time.time()
        if existing.status == "irreversible":
            # Compensating action required; we never auto-undo these. Record a
            # note on the trail but leave status unchanged.
            self._append_event(
                action_id,
                "irreversible",
                "irreversible",
                ts,
                "revert requested; compensating action required",
            )
            self._conn.commit()
            return existing
        handler = _handlers.get_undo_handler(existing.action_type)
        if handler is None:
            raise RollbackError(
                f"No undo handler for action_type {existing.action_type!r}."
            )
        try:
            handler(existing.undo_payload)
        except Exception as exc:  # noqa: BLE001 - capture + mark failed
            self._conn.execute(
                "UPDATE reversible_actions SET status = 'failed',"
                " revert_note = ? WHERE id = ?",
                (f"undo failed: {exc}", action_id),
            )
            self._append_event(
                action_id, existing.status, "failed", ts, f"undo failed: {exc}"
            )
            self._conn.commit()
            raise RollbackError(f"Undo failed for {action_id!r}: {exc}") from exc
        self._conn.execute(
            "UPDATE reversible_actions SET status = 'reverted',"
            " reverted_at = ?, revert_note = ? WHERE id = ?",
            (ts, str(note or "").strip() or None, action_id),
        )
        self._append_event(
            action_id, existing.status, "reverted", ts, note or "reverted"
        )
        self._conn.commit()
        result = self.get(action_id)
        assert result is not None
        return result

    def close(self) -> None:
        self._conn.close()
