"""EventLogStore — append-only SQLite persistence for EventBus events.

Mirrors the subscribe-to-bus + persist pattern of ``traces/store.py`` and the
swallow-and-log failure isolation of ``agents/approvals.py``. The bus stays the
live source of truth; this store is durable, queryable history.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from openjarvis.core.events import Event, EventBus, EventType

logger = logging.getLogger(__name__)

# Ordered key aliases per correlation column; first present scalar wins.
_ID_ALIASES: Dict[str, tuple[str, ...]] = {
    "agent_id": ("agent_id", "agent"),
    "task_id": ("task_id", "task"),
    "project_id": ("project_id", "project"),
    "run_id": ("run_id", "correlation_id"),
}

_CREATE = """\
CREATE TABLE IF NOT EXISTS event_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type  TEXT NOT NULL,
    timestamp   REAL NOT NULL,
    agent_id    TEXT,
    task_id     TEXT,
    project_id  TEXT,
    run_id      TEXT,
    data        TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_eventlog_type ON event_log(event_type);
CREATE INDEX IF NOT EXISTS idx_eventlog_ts ON event_log(timestamp);
CREATE INDEX IF NOT EXISTS idx_eventlog_agent ON event_log(agent_id);
CREATE INDEX IF NOT EXISTS idx_eventlog_task ON event_log(task_id);
CREATE INDEX IF NOT EXISTS idx_eventlog_project ON event_log(project_id);
CREATE INDEX IF NOT EXISTS idx_eventlog_run ON event_log(run_id);
"""


@dataclass(slots=True)
class EventRecord:
    """A single persisted event row."""

    id: int
    event_type: str
    timestamp: float
    data: Dict[str, Any]
    agent_id: Optional[str] = None
    task_id: Optional[str] = None
    project_id: Optional[str] = None
    run_id: Optional[str] = None


def _safe(obj: Any) -> str:
    """Fallback JSON encoder for non-serializable payload values."""
    text = repr(obj)
    return text if len(text) <= 2000 else text[:1997] + "..."


def _extract_id(data: Dict[str, Any], aliases: tuple[str, ...]) -> Optional[str]:
    """Return the first alias whose value is a non-empty scalar, else None."""
    for key in aliases:
        if key in data:
            value = data[key]
            if isinstance(value, (str, int, float)) and not isinstance(value, bool):
                text = str(value).strip()
                if text:
                    return text
    return None


class EventLogStore:
    """Append-only SQLite store for EventBus events."""

    def __init__(self, db_path: str = "") -> None:
        if not db_path:
            db_path = str(Path.home() / ".openjarvis" / "eventlog.db")
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(_CREATE)
        self._conn.commit()

    def subscribe_to_bus(
        self,
        bus: EventBus,
        *,
        denylist: Sequence[str] = (),
    ) -> None:
        """Subscribe ``record`` to every EventType whose value is not denied."""
        denied = set(denylist)
        for event_type in EventType:
            if event_type.value in denied:
                continue
            bus.subscribe(event_type, self.record)

    def record(self, event: Event) -> None:
        """Persist one event. Never raises — failures are logged and dropped."""
        try:
            data = event.data or {}
            payload = json.dumps(data, default=_safe)
            event_type = (
                event.event_type.value
                if isinstance(event.event_type, EventType)
                else str(event.event_type)
            )
            self._conn.execute(
                "INSERT INTO event_log"
                " (event_type, timestamp, agent_id, task_id, project_id, run_id, data)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    event_type,
                    float(event.timestamp),
                    _extract_id(data, _ID_ALIASES["agent_id"]),
                    _extract_id(data, _ID_ALIASES["task_id"]),
                    _extract_id(data, _ID_ALIASES["project_id"]),
                    _extract_id(data, _ID_ALIASES["run_id"]),
                    payload,
                ),
            )
            self._conn.commit()
        except Exception:  # noqa: BLE001 - capture must never crash the publisher
            logger.exception("EventLogStore.record failed for %s", event)

    def _row(self, row: sqlite3.Row) -> EventRecord:
        return EventRecord(
            id=row["id"],
            event_type=row["event_type"],
            timestamp=row["timestamp"],
            agent_id=row["agent_id"],
            task_id=row["task_id"],
            project_id=row["project_id"],
            run_id=row["run_id"],
            data=json.loads(row["data"]),
        )

    def query(
        self,
        *,
        event_type: Optional[str] = None,
        agent_id: Optional[str] = None,
        task_id: Optional[str] = None,
        project_id: Optional[str] = None,
        run_id: Optional[str] = None,
        since: Optional[float] = None,
        until: Optional[float] = None,
        limit: int = 100,
    ) -> List[EventRecord]:
        clauses: List[str] = []
        params: List[Any] = []
        for col, val in (
            ("event_type", event_type),
            ("agent_id", agent_id),
            ("task_id", task_id),
            ("project_id", project_id),
            ("run_id", run_id),
        ):
            if val is not None:
                clauses.append(f"{col} = ?")
                params.append(val)
        if since is not None:
            clauses.append("timestamp >= ?")
            params.append(since)
        if until is not None:
            clauses.append("timestamp <= ?")
            params.append(until)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        params.append(limit)
        rows = self._conn.execute(
            f"SELECT * FROM event_log{where} ORDER BY timestamp DESC, id DESC LIMIT ?",
            params,
        ).fetchall()
        return [self._row(r) for r in rows]

    def feed(
        self,
        *,
        limit: int = 50,
        since: Optional[float] = None,
    ) -> List[EventRecord]:
        """Return the newest events across all types (activity feed)."""
        return self.query(since=since, limit=limit)

    def count(self) -> int:
        row = self._conn.execute("SELECT COUNT(*) FROM event_log").fetchone()
        return row[0] if row else 0

    def close(self) -> None:
        self._conn.close()
