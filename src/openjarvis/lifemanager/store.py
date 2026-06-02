"""LifeStore — SQLite store for life domains and recurring routines.

Two tables: ``life_domains`` and ``routines`` (with completion-time cadence
math). Follows the patterns of ``eventlog/store.py``,
``approvals_center/store.py`` and ``codelink/store.py``.
"""

from __future__ import annotations

import re
import sqlite3
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

_VALID_CADENCES = {"daily", "weekly", "monthly", "custom"}
_VALID_STATUSES = {"active", "paused", "archived"}
_CADENCE_DAYS = {"daily": 1, "weekly": 7, "monthly": 30}
_DAY_SECONDS = 86400.0

_CREATE = """\
CREATE TABLE IF NOT EXISTS life_domains (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    slug        TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    created_at  REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ld_slug ON life_domains(slug);
CREATE TABLE IF NOT EXISTS routines (
    id            TEXT PRIMARY KEY,
    domain_id     TEXT,
    title         TEXT NOT NULL,
    cadence       TEXT NOT NULL DEFAULT 'daily',
    interval_days INTEGER NOT NULL DEFAULT 1,
    status        TEXT NOT NULL DEFAULT 'active',
    next_due_at   REAL,
    last_done_at  REAL,
    streak        INTEGER NOT NULL DEFAULT 0,
    created_at    REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_rt_domain ON routines(domain_id);
CREATE INDEX IF NOT EXISTS idx_rt_status ON routines(status);
CREATE INDEX IF NOT EXISTS idx_rt_due ON routines(next_due_at);
"""


class LifeError(ValueError):
    """Raised on invalid cadence/status or missing records."""


def _slugify(value: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", str(value or "").strip().lower()).strip("-")
    return s or "domain"


@dataclass(slots=True)
class LifeDomain:
    id: str
    name: str
    slug: str
    created_at: float
    description: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "slug": self.slug,
            "description": self.description,
            "created_at": self.created_at,
        }


@dataclass(slots=True)
class Routine:
    id: str
    title: str
    cadence: str
    interval_days: int
    status: str
    created_at: float
    domain_id: Optional[str] = None
    next_due_at: Optional[float] = None
    last_done_at: Optional[float] = None
    streak: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "cadence": self.cadence,
            "interval_days": self.interval_days,
            "status": self.status,
            "created_at": self.created_at,
            "domain_id": self.domain_id,
            "next_due_at": self.next_due_at,
            "last_done_at": self.last_done_at,
            "streak": self.streak,
        }


class LifeStore:
    """SQLite store for life domains and routines."""

    def __init__(self, db_path: str = "") -> None:
        if not db_path:
            db_path = str(Path.home() / ".openjarvis" / "lifemanager.db")
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(_CREATE)
        self._conn.commit()

    # -- domains --------------------------------------------------------

    def _domain_row(self, row: sqlite3.Row) -> LifeDomain:
        return LifeDomain(
            id=row["id"],
            name=row["name"],
            slug=row["slug"],
            created_at=row["created_at"],
            description=row["description"],
        )

    def add_domain(
        self,
        *,
        name: str,
        slug: str = "",
        description: str = "",
        now: Optional[float] = None,
    ) -> LifeDomain:
        name = str(name or "").strip()
        if not name:
            raise ValueError("name is required")
        ts = now if now is not None else time.time()
        d = LifeDomain(
            id=uuid.uuid4().hex[:12],
            name=name,
            slug=_slugify(slug) if slug else _slugify(name),
            created_at=ts,
            description=str(description or ""),
        )
        self._conn.execute(
            "INSERT INTO life_domains (id, name, slug, description, created_at)"
            " VALUES (?, ?, ?, ?, ?)",
            (d.id, d.name, d.slug, d.description, d.created_at),
        )
        self._conn.commit()
        return d

    def get_domain(self, domain_id: str) -> Optional[LifeDomain]:
        row = self._conn.execute(
            "SELECT * FROM life_domains WHERE id = ?", (domain_id,)
        ).fetchone()
        return self._domain_row(row) if row else None

    def list_domains(self) -> List[LifeDomain]:
        rows = self._conn.execute(
            "SELECT * FROM life_domains ORDER BY created_at ASC"
        ).fetchall()
        return [self._domain_row(r) for r in rows]

    # -- routines -------------------------------------------------------

    def _routine_row(self, row: sqlite3.Row) -> Routine:
        return Routine(
            id=row["id"],
            title=row["title"],
            cadence=row["cadence"],
            interval_days=row["interval_days"],
            status=row["status"],
            created_at=row["created_at"],
            domain_id=row["domain_id"],
            next_due_at=row["next_due_at"],
            last_done_at=row["last_done_at"],
            streak=row["streak"],
        )

    @staticmethod
    def _interval_days(cadence: str, interval_days: int) -> int:
        if cadence == "custom":
            if int(interval_days) < 1:
                raise LifeError("interval_days must be >= 1 for custom cadence")
            return int(interval_days)
        return _CADENCE_DAYS[cadence]

    def add_routine(
        self,
        *,
        title: str,
        domain_id: str = "",
        cadence: str = "daily",
        interval_days: int = 1,
        next_due_at: Optional[float] = None,
        now: Optional[float] = None,
    ) -> Routine:
        title = str(title or "").strip()
        if not title:
            raise ValueError("title is required")
        if cadence not in _VALID_CADENCES:
            raise LifeError(
                f"cadence must be one of {sorted(_VALID_CADENCES)}, got {cadence!r}"
            )
        resolved_interval = self._interval_days(cadence, interval_days)
        ts = now if now is not None else time.time()
        r = Routine(
            id=uuid.uuid4().hex[:12],
            title=title,
            cadence=cadence,
            interval_days=resolved_interval,
            status="active",
            created_at=ts,
            domain_id=domain_id or None,
            next_due_at=next_due_at,
            last_done_at=None,
            streak=0,
        )
        self._conn.execute(
            "INSERT INTO routines"
            " (id, domain_id, title, cadence, interval_days, status,"
            " next_due_at, last_done_at, streak, created_at)"
            " VALUES (?, ?, ?, ?, ?, 'active', ?, NULL, 0, ?)",
            (
                r.id,
                r.domain_id,
                r.title,
                r.cadence,
                r.interval_days,
                r.next_due_at,
                r.created_at,
            ),
        )
        self._conn.commit()
        return r

    def get_routine(self, routine_id: str) -> Optional[Routine]:
        row = self._conn.execute(
            "SELECT * FROM routines WHERE id = ?", (routine_id,)
        ).fetchone()
        return self._routine_row(row) if row else None

    def list_routines(
        self,
        *,
        domain_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 100,
    ) -> List[Routine]:
        clauses: List[str] = []
        params: List[Any] = []
        if domain_id is not None:
            clauses.append("domain_id = ?")
            params.append(domain_id)
        if status is not None:
            clauses.append("status = ?")
            params.append(status)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        params.append(limit)
        rows = self._conn.execute(
            f"SELECT * FROM routines{where} ORDER BY created_at ASC LIMIT ?",
            params,
        ).fetchall()
        return [self._routine_row(r) for r in rows]

    def complete_routine(
        self, routine_id: str, *, now: Optional[float] = None
    ) -> Routine:
        existing = self.get_routine(routine_id)
        if existing is None:
            raise LifeError(f"Routine not found: {routine_id!r}")
        ts = now if now is not None else time.time()
        interval = self._interval_days(existing.cadence, existing.interval_days)
        next_due = ts + interval * _DAY_SECONDS
        self._conn.execute(
            "UPDATE routines SET last_done_at = ?, next_due_at = ?,"
            " streak = streak + 1 WHERE id = ?",
            (ts, next_due, routine_id),
        )
        self._conn.commit()
        result = self.get_routine(routine_id)
        assert result is not None
        return result

    def set_routine_status(
        self, routine_id: str, status: str, *, now: Optional[float] = None
    ) -> Routine:
        if status not in _VALID_STATUSES:
            raise LifeError(
                f"status must be one of {sorted(_VALID_STATUSES)}, got {status!r}"
            )
        existing = self.get_routine(routine_id)
        if existing is None:
            raise LifeError(f"Routine not found: {routine_id!r}")
        self._conn.execute(
            "UPDATE routines SET status = ? WHERE id = ?", (status, routine_id)
        )
        self._conn.commit()
        result = self.get_routine(routine_id)
        assert result is not None
        return result

    def due(self, *, now: Optional[float] = None, limit: int = 100) -> List[Routine]:
        ts = now if now is not None else time.time()
        rows = self._conn.execute(
            "SELECT * FROM routines WHERE status = 'active'"
            " AND (next_due_at IS NULL OR next_due_at <= ?)"
            " ORDER BY next_due_at IS NULL DESC, next_due_at ASC LIMIT ?",
            (ts, limit),
        ).fetchall()
        return [self._routine_row(r) for r in rows]

    def close(self) -> None:
        self._conn.close()
