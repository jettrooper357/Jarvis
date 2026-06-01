"""DecisionLogStore — append-only SQLite log of decisions and approvals.

Decisions are immutable rows. A new decision may ``supersede`` a prior one,
which flips the prior row's status to ``superseded`` (the only mutation).
"""

from __future__ import annotations

import sqlite3
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from openjarvis.core.events import EventBus, EventType

_VALID_STATUSES = {"active", "superseded", "revoked"}

_CREATE = """\
CREATE TABLE IF NOT EXISTS decisions (
    id TEXT PRIMARY KEY,
    statement TEXT NOT NULL,
    rationale TEXT NOT NULL DEFAULT '',
    decided_by TEXT NOT NULL DEFAULT '',
    approved_by TEXT NOT NULL DEFAULT '',
    decided_at REAL NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    source_ref TEXT NOT NULL DEFAULT '',
    linked_task_id TEXT NOT NULL DEFAULT '',
    linked_project_id TEXT NOT NULL DEFAULT '',
    supersedes TEXT NOT NULL DEFAULT ''
);
"""


@dataclass(slots=True)
class Decision:
    """An immutable record of a decision or approval."""

    id: str
    statement: str
    rationale: str
    decided_by: str
    decided_at: float
    status: str = "active"
    approved_by: str = ""
    source_ref: str = ""
    linked_task_id: str = ""
    linked_project_id: str = ""
    supersedes: str = ""


class DecisionLogStore:
    """SQLite store for the decision log."""

    def __init__(self, db_path: str = "", bus: Optional[EventBus] = None) -> None:
        if not db_path:
            db_path = str(Path.home() / ".openjarvis" / "decisions.db")
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(_CREATE)
        self._conn.commit()
        self._bus = bus

    def _publish(self, event_type: EventType, detail: dict) -> None:
        if self._bus is not None:
            self._bus.publish(event_type, detail)

    def _row(self, row: sqlite3.Row) -> Decision:
        return Decision(
            id=row["id"],
            statement=row["statement"],
            rationale=row["rationale"],
            decided_by=row["decided_by"],
            decided_at=row["decided_at"],
            status=row["status"],
            approved_by=row["approved_by"],
            source_ref=row["source_ref"],
            linked_task_id=row["linked_task_id"],
            linked_project_id=row["linked_project_id"],
            supersedes=row["supersedes"],
        )

    def record(
        self,
        *,
        statement: str,
        rationale: str = "",
        decided_by: str = "",
        approved_by: str = "",
        source_ref: str = "",
        linked_task_id: str = "",
        linked_project_id: str = "",
        supersedes: str = "",
        now: Optional[float] = None,
    ) -> Decision:
        statement = str(statement or "").strip()
        if not statement:
            raise ValueError("statement is required")
        ts = now if now is not None else time.time()
        did = uuid.uuid4().hex[:16]
        d = Decision(
            id=did,
            statement=statement,
            rationale=str(rationale or "").strip(),
            decided_by=str(decided_by or "").strip(),
            decided_at=ts,
            status="active",
            approved_by=str(approved_by or "").strip(),
            source_ref=source_ref,
            linked_task_id=linked_task_id,
            linked_project_id=linked_project_id,
            supersedes=str(supersedes or "").strip(),
        )
        self._conn.execute(
            "INSERT INTO decisions"
            " (id, statement, rationale, decided_by, approved_by,"
            " decided_at, status, source_ref, linked_task_id,"
            " linked_project_id, supersedes)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                d.id,
                d.statement,
                d.rationale,
                d.decided_by,
                d.approved_by,
                d.decided_at,
                d.status,
                d.source_ref,
                d.linked_task_id,
                d.linked_project_id,
                d.supersedes,
            ),
        )
        if d.supersedes:
            self._conn.execute(
                "UPDATE decisions SET status = 'superseded' WHERE id = ?",
                (d.supersedes,),
            )
            self._publish(
                EventType.DECISION_SUPERSEDED,
                {"id": d.supersedes, "by": d.id},
            )
        self._conn.commit()
        self._publish(
            EventType.DECISION_RECORDED,
            {"id": d.id, "statement": d.statement},
        )
        return d

    def get(self, decision_id: str) -> Optional[Decision]:
        row = self._conn.execute(
            "SELECT * FROM decisions WHERE id = ?", (decision_id,)
        ).fetchone()
        return self._row(row) if row is not None else None

    def list(
        self,
        *,
        linked_project_id: Optional[str] = None,
        linked_task_id: Optional[str] = None,
        status: Optional[str] = None,
    ) -> List[Decision]:
        clauses: List[str] = []
        params: List[object] = []
        if linked_project_id:
            clauses.append("linked_project_id = ?")
            params.append(linked_project_id)
        if linked_task_id:
            clauses.append("linked_task_id = ?")
            params.append(linked_task_id)
        if status:
            if status not in _VALID_STATUSES:
                raise ValueError(f"status must be one of {sorted(_VALID_STATUSES)}")
            clauses.append("status = ?")
            params.append(status)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        rows = self._conn.execute(
            f"SELECT * FROM decisions{where} ORDER BY decided_at ASC", params
        ).fetchall()
        return [self._row(r) for r in rows]

    def close(self) -> None:
        self._conn.close()
