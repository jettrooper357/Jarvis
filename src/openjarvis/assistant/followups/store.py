"""FollowUpStore — SQLite-backed tracker for "waiting on" / "owe reply" items.

Append-only event trail (``followup_events``) plus a maintained current-state
row (``followups``). Follows the WAL + idempotent-migrate pattern from
``agents/digest_store.py`` and the optional-bus pattern from
``agents/approvals.py``.
"""

from __future__ import annotations

import sqlite3
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from openjarvis.core.events import EventBus, EventType

_VALID_DIRECTIONS = {"waiting_on", "owe_reply"}

_CREATE = """\
CREATE TABLE IF NOT EXISTS followups (
    id TEXT PRIMARY KEY,
    summary TEXT NOT NULL,
    counterparty TEXT NOT NULL DEFAULT '',
    direction TEXT NOT NULL DEFAULT 'waiting_on',
    status TEXT NOT NULL DEFAULT 'open',
    source_ref TEXT NOT NULL DEFAULT '',
    linked_task_id TEXT NOT NULL DEFAULT '',
    linked_project_id TEXT NOT NULL DEFAULT '',
    created_at REAL NOT NULL,
    sla_due_at REAL,
    last_activity_at REAL NOT NULL,
    resolved_at REAL
);
CREATE TABLE IF NOT EXISTS followup_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    followup_id TEXT NOT NULL,
    event TEXT NOT NULL,
    at REAL NOT NULL,
    detail TEXT NOT NULL DEFAULT ''
);
"""


@dataclass(slots=True)
class FollowUp:
    """A single follow-up item the assistant is tracking."""

    id: str
    summary: str
    counterparty: str
    direction: str
    status: str
    created_at: float
    last_activity_at: float
    source_ref: str = ""
    linked_task_id: str = ""
    linked_project_id: str = ""
    sla_due_at: Optional[float] = None
    resolved_at: Optional[float] = None


class FollowUpStore:
    """SQLite store for follow-up items with an append-only event trail."""

    def __init__(self, db_path: str = "", bus: Optional[EventBus] = None) -> None:
        if not db_path:
            db_path = str(Path.home() / ".openjarvis" / "followups.db")
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(_CREATE)
        self._conn.commit()
        self._bus = bus

    def _publish(self, event_type: EventType, detail: dict) -> None:
        if self._bus is not None:
            self._bus.publish(event_type, detail)

    def _row(self, row: sqlite3.Row) -> FollowUp:
        return FollowUp(
            id=row["id"],
            summary=row["summary"],
            counterparty=row["counterparty"],
            direction=row["direction"],
            status=row["status"],
            created_at=row["created_at"],
            last_activity_at=row["last_activity_at"],
            source_ref=row["source_ref"],
            linked_task_id=row["linked_task_id"],
            linked_project_id=row["linked_project_id"],
            sla_due_at=row["sla_due_at"],
            resolved_at=row["resolved_at"],
        )

    def _append_event(
        self, followup_id: str, event: str, at: float, detail: str = ""
    ) -> None:
        self._conn.execute(
            "INSERT INTO followup_events (followup_id, event, at, detail)"
            " VALUES (?, ?, ?, ?)",
            (followup_id, event, at, detail),
        )

    def add(
        self,
        *,
        summary: str,
        counterparty: str,
        direction: str = "waiting_on",
        source_ref: str = "",
        linked_task_id: str = "",
        linked_project_id: str = "",
        sla_due_at: Optional[float] = None,
        now: Optional[float] = None,
    ) -> FollowUp:
        if direction not in _VALID_DIRECTIONS:
            raise ValueError(
                f"direction must be one of {sorted(_VALID_DIRECTIONS)},"
                f" got {direction!r}"
            )
        summary = str(summary or "").strip()
        if not summary:
            raise ValueError("summary is required")
        ts = now if now is not None else time.time()
        fid = uuid.uuid4().hex[:16]
        fu = FollowUp(
            id=fid,
            summary=summary,
            counterparty=str(counterparty or "").strip(),
            direction=direction,
            status="open",
            created_at=ts,
            last_activity_at=ts,
            source_ref=source_ref,
            linked_task_id=linked_task_id,
            linked_project_id=linked_project_id,
            sla_due_at=sla_due_at,
        )
        self._conn.execute(
            "INSERT INTO followups (id, summary, counterparty, direction, status,"
            " source_ref, linked_task_id, linked_project_id, created_at, sla_due_at,"
            " last_activity_at, resolved_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                fu.id,
                fu.summary,
                fu.counterparty,
                fu.direction,
                fu.status,
                fu.source_ref,
                fu.linked_task_id,
                fu.linked_project_id,
                fu.created_at,
                fu.sla_due_at,
                fu.last_activity_at,
                fu.resolved_at,
            ),
        )
        self._append_event(fid, "created", ts)
        self._conn.commit()
        self._publish(
            EventType.FOLLOWUP_CREATED,
            {"id": fid, "summary": fu.summary, "counterparty": fu.counterparty},
        )
        return fu

    def get(self, followup_id: str) -> Optional[FollowUp]:
        row = self._conn.execute(
            "SELECT * FROM followups WHERE id = ?", (followup_id,)
        ).fetchone()
        return self._row(row) if row is not None else None

    def list(
        self,
        *,
        status: Optional[str] = None,
        counterparty: Optional[str] = None,
        stale_only: bool = False,
        now: Optional[float] = None,
    ) -> List[FollowUp]:
        clauses: List[str] = []
        params: List[object] = []
        if status:
            clauses.append("status = ?")
            params.append(status)
        if counterparty:
            clauses.append("counterparty = ?")
            params.append(counterparty)
        if stale_only:
            ts = now if now is not None else time.time()
            clauses.append("status IN ('open', 'nudged')")
            clauses.append("sla_due_at IS NOT NULL AND sla_due_at <= ?")
            params.append(ts)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        rows = self._conn.execute(
            f"SELECT * FROM followups{where} ORDER BY created_at ASC", params
        ).fetchall()
        return [self._row(r) for r in rows]

    def resolve(
        self,
        followup_id: str,
        *,
        status: str = "resolved",
        now: Optional[float] = None,
    ) -> Optional[FollowUp]:
        if status not in ("resolved", "cancelled"):
            raise ValueError("resolve status must be 'resolved' or 'cancelled'")
        existing = self.get(followup_id)
        if existing is None:
            return None
        ts = now if now is not None else time.time()
        self._conn.execute(
            "UPDATE followups SET status = ?, resolved_at = ?, last_activity_at = ?"
            " WHERE id = ?",
            (status, ts, ts, followup_id),
        )
        self._append_event(followup_id, status, ts)
        self._conn.commit()
        self._publish(
            EventType.FOLLOWUP_RESOLVED, {"id": followup_id, "status": status}
        )
        return self.get(followup_id)

    def sweep_stale(self, *, now: Optional[float] = None) -> List[FollowUp]:
        ts = now if now is not None else time.time()
        rows = self._conn.execute(
            "SELECT * FROM followups WHERE status = 'open'"
            " AND sla_due_at IS NOT NULL AND sla_due_at <= ?"
            " ORDER BY created_at ASC",
            (ts,),
        ).fetchall()
        nudged: List[FollowUp] = []
        for row in rows:
            self._conn.execute(
                "UPDATE followups SET status = 'nudged', last_activity_at = ?"
                " WHERE id = ?",
                (ts, row["id"]),
            )
            self._append_event(row["id"], "nudged", ts)
            nudged.append(self.get(row["id"]))  # type: ignore[arg-type]
        if nudged:
            self._conn.commit()
            for fu in nudged:
                self._publish(
                    EventType.FOLLOWUP_UPDATED,
                    {"id": fu.id, "status": "nudged"},
                )
        return nudged

    def close(self) -> None:
        self._conn.close()
