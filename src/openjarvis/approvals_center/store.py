"""ActionApprovalStore — generalized action-approval queue.

Append-only SQLite-WAL store with two tables: ``action_approvals`` (current
state) and ``action_approval_events`` (immutable transition trail). Distinct
from the tool-gating ``agents/approvals.py`` store. Follows the patterns of
``eventlog/store.py`` and ``agents/approvals.py``.
"""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

_TERMINAL = ("approved", "rejected")
_REOPENABLE = ("deferred", "needs_info", "modified")

_CREATE = """\
CREATE TABLE IF NOT EXISTS action_approvals (
    id                TEXT PRIMARY KEY,
    action_type       TEXT NOT NULL,
    summary           TEXT NOT NULL DEFAULT '',
    payload           TEXT NOT NULL DEFAULT '{}',
    state             TEXT NOT NULL DEFAULT 'pending',
    agent_id          TEXT,
    task_id           TEXT,
    project_id        TEXT,
    requested_by      TEXT,
    requested_at      REAL NOT NULL,
    resolved_by       TEXT,
    resolved_at       REAL,
    decision_reason   TEXT,
    followup_question TEXT,
    remind_at         REAL,
    revision          INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_aa_type ON action_approvals(action_type);
CREATE INDEX IF NOT EXISTS idx_aa_state ON action_approvals(state);
CREATE INDEX IF NOT EXISTS idx_aa_agent ON action_approvals(agent_id);
CREATE INDEX IF NOT EXISTS idx_aa_task ON action_approvals(task_id);
CREATE INDEX IF NOT EXISTS idx_aa_project ON action_approvals(project_id);
CREATE TABLE IF NOT EXISTS action_approval_events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    approval_id TEXT NOT NULL,
    from_state  TEXT NOT NULL,
    to_state    TEXT NOT NULL,
    actor       TEXT,
    at          REAL NOT NULL,
    detail      TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_aae_approval ON action_approval_events(approval_id);
"""


class ActionApprovalError(ValueError):
    """Raised on invalid transitions or missing approvals."""


@dataclass(slots=True)
class ActionApproval:
    """A single action awaiting (or having received) a human decision."""

    id: str
    action_type: str
    summary: str
    state: str
    requested_at: float
    payload: Dict[str, Any] = field(default_factory=dict)
    agent_id: Optional[str] = None
    task_id: Optional[str] = None
    project_id: Optional[str] = None
    requested_by: Optional[str] = None
    resolved_by: Optional[str] = None
    resolved_at: Optional[float] = None
    decision_reason: Optional[str] = None
    followup_question: Optional[str] = None
    remind_at: Optional[float] = None
    revision: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "action_type": self.action_type,
            "summary": self.summary,
            "state": self.state,
            "payload": dict(self.payload),
            "agent_id": self.agent_id,
            "task_id": self.task_id,
            "project_id": self.project_id,
            "requested_by": self.requested_by,
            "requested_at": self.requested_at,
            "resolved_by": self.resolved_by,
            "resolved_at": self.resolved_at,
            "decision_reason": self.decision_reason,
            "followup_question": self.followup_question,
            "remind_at": self.remind_at,
            "revision": self.revision,
        }


class ActionApprovalStore:
    """SQLite store for generalized action approvals."""

    def __init__(self, db_path: str = "") -> None:
        if not db_path:
            db_path = str(Path.home() / ".openjarvis" / "action_approvals.db")
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(_CREATE)
        self._conn.commit()

    # -- internals ------------------------------------------------------

    def _row(self, row: sqlite3.Row) -> ActionApproval:
        return ActionApproval(
            id=row["id"],
            action_type=row["action_type"],
            summary=row["summary"],
            state=row["state"],
            requested_at=row["requested_at"],
            payload=json.loads(row["payload"]) if row["payload"] else {},
            agent_id=row["agent_id"],
            task_id=row["task_id"],
            project_id=row["project_id"],
            requested_by=row["requested_by"],
            resolved_by=row["resolved_by"],
            resolved_at=row["resolved_at"],
            decision_reason=row["decision_reason"],
            followup_question=row["followup_question"],
            remind_at=row["remind_at"],
            revision=row["revision"],
        )

    def _append_event(
        self,
        approval_id: str,
        from_state: str,
        to_state: str,
        at: float,
        actor: Optional[str] = None,
        detail: str = "",
    ) -> None:
        self._conn.execute(
            "INSERT INTO action_approval_events"
            " (approval_id, from_state, to_state, actor, at, detail)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (approval_id, from_state, to_state, actor, at, detail),
        )

    # -- create / read --------------------------------------------------

    def request(
        self,
        *,
        action_type: str,
        summary: str,
        payload: Optional[Dict[str, Any]] = None,
        agent_id: str = "",
        task_id: str = "",
        project_id: str = "",
        requested_by: str = "",
        now: Optional[float] = None,
    ) -> ActionApproval:
        action_type = str(action_type or "").strip()
        summary = str(summary or "").strip()
        if not action_type:
            raise ValueError("action_type is required")
        if not summary:
            raise ValueError("summary is required")
        ts = now if now is not None else time.time()
        aid = uuid.uuid4().hex[:12]
        a = ActionApproval(
            id=aid,
            action_type=action_type,
            summary=summary,
            state="pending",
            requested_at=ts,
            payload=dict(payload or {}),
            agent_id=agent_id or None,
            task_id=task_id or None,
            project_id=project_id or None,
            requested_by=requested_by or None,
        )
        self._conn.execute(
            "INSERT INTO action_approvals"
            " (id, action_type, summary, payload, state, agent_id, task_id,"
            " project_id, requested_by, requested_at, revision)"
            " VALUES (?, ?, ?, ?, 'pending', ?, ?, ?, ?, ?, 0)",
            (
                a.id,
                a.action_type,
                a.summary,
                json.dumps(a.payload),
                a.agent_id,
                a.task_id,
                a.project_id,
                a.requested_by,
                a.requested_at,
            ),
        )
        self._append_event(aid, "", "pending", ts, requested_by or None, "created")
        self._conn.commit()
        return a

    def get(self, approval_id: str) -> Optional[ActionApproval]:
        row = self._conn.execute(
            "SELECT * FROM action_approvals WHERE id = ?", (approval_id,)
        ).fetchone()
        return self._row(row) if row else None

    def history(self, approval_id: str) -> List[Dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT from_state, to_state, actor, at, detail"
            " FROM action_approval_events WHERE approval_id = ?"
            " ORDER BY id ASC",
            (approval_id,),
        ).fetchall()
        return [
            {
                "from_state": r["from_state"],
                "to_state": r["to_state"],
                "actor": r["actor"],
                "at": r["at"],
                "detail": r["detail"],
            }
            for r in rows
        ]

    def list(
        self,
        *,
        action_type: Optional[str] = None,
        state: Optional[str] = None,
        agent_id: Optional[str] = None,
        project_id: Optional[str] = None,
        limit: int = 100,
    ) -> List[ActionApproval]:
        clauses: List[str] = []
        params: List[Any] = []
        for col, val in (
            ("action_type", action_type),
            ("state", state),
            ("agent_id", agent_id),
            ("project_id", project_id),
        ):
            if val is not None:
                clauses.append(f"{col} = ?")
                params.append(val)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        params.append(limit)
        rows = self._conn.execute(
            f"SELECT * FROM action_approvals{where}"
            f" ORDER BY requested_at DESC, id DESC LIMIT ?",
            params,
        ).fetchall()
        return [self._row(r) for r in rows]

    def _transition(
        self,
        approval_id: str,
        to_state: str,
        *,
        allowed_from: tuple[str, ...],
        now: Optional[float],
        resolved_by: Optional[str] = None,
        reason: Optional[str] = None,
        extra_sets: str = "",
        extra_params: tuple[Any, ...] = (),
        detail: str = "",
        mark_resolved: bool = True,
    ) -> ActionApproval:
        existing = self.get(approval_id)
        if existing is None:
            raise ActionApprovalError(f"Approval not found: {approval_id!r}")
        if existing.state not in allowed_from:
            raise ActionApprovalError(
                f"Approval {approval_id!r} is {existing.state}; cannot move to "
                f"{to_state} (allowed from {allowed_from})."
            )
        ts = now if now is not None else time.time()
        sets = ["state = ?"]
        params: List[Any] = [to_state]
        if mark_resolved:
            sets += ["resolved_by = ?", "resolved_at = ?", "decision_reason = ?"]
            params += [
                str(resolved_by or "").strip() or None,
                ts,
                str(reason or "").strip() or None,
            ]
        if extra_sets:
            sets.append(extra_sets)
            params.extend(extra_params)
        params.append(approval_id)
        self._conn.execute(
            f"UPDATE action_approvals SET {', '.join(sets)} WHERE id = ?",
            params,
        )
        self._append_event(
            approval_id,
            existing.state,
            to_state,
            ts,
            str(resolved_by or "").strip() or None,
            detail or reason or "",
        )
        self._conn.commit()
        result = self.get(approval_id)
        assert result is not None
        return result

    def approve(
        self,
        approval_id: str,
        *,
        resolved_by: Optional[str] = None,
        reason: Optional[str] = None,
        now: Optional[float] = None,
    ) -> ActionApproval:
        return self._transition(
            approval_id,
            "approved",
            allowed_from=("pending",),
            now=now,
            resolved_by=resolved_by,
            reason=reason,
        )

    def reject(
        self,
        approval_id: str,
        *,
        resolved_by: Optional[str] = None,
        reason: Optional[str] = None,
        now: Optional[float] = None,
    ) -> ActionApproval:
        return self._transition(
            approval_id,
            "rejected",
            allowed_from=("pending",),
            now=now,
            resolved_by=resolved_by,
            reason=reason,
        )

    def defer(
        self,
        approval_id: str,
        *,
        remind_at: Optional[float] = None,
        resolved_by: Optional[str] = None,
        reason: Optional[str] = None,
        now: Optional[float] = None,
    ) -> ActionApproval:
        return self._transition(
            approval_id,
            "deferred",
            allowed_from=("pending",),
            now=now,
            resolved_by=resolved_by,
            reason=reason,
            extra_sets="remind_at = ?",
            extra_params=(remind_at,),
            detail="deferred",
        )

    def ask(
        self,
        approval_id: str,
        *,
        question: str,
        resolved_by: Optional[str] = None,
        now: Optional[float] = None,
    ) -> ActionApproval:
        question = str(question or "").strip()
        if not question:
            raise ActionApprovalError("ask requires a non-empty question")
        return self._transition(
            approval_id,
            "needs_info",
            allowed_from=("pending",),
            now=now,
            resolved_by=resolved_by,
            extra_sets="followup_question = ?",
            extra_params=(question,),
            detail=f"asked: {question}",
        )

    def modify(
        self,
        approval_id: str,
        *,
        new_payload: Dict[str, Any],
        resolved_by: Optional[str] = None,
        reason: Optional[str] = None,
        now: Optional[float] = None,
    ) -> ActionApproval:
        existing = self.get(approval_id)
        if existing is None:
            raise ActionApprovalError(f"Approval not found: {approval_id!r}")
        return self._transition(
            approval_id,
            "modified",
            allowed_from=("pending",),
            now=now,
            resolved_by=resolved_by,
            reason=reason,
            extra_sets="payload = ?, revision = ?",
            extra_params=(json.dumps(dict(new_payload)), existing.revision + 1),
            detail="modified payload",
        )

    def reopen(
        self,
        approval_id: str,
        *,
        resolved_by: Optional[str] = None,
        reason: Optional[str] = None,
        now: Optional[float] = None,
    ) -> ActionApproval:
        return self._transition(
            approval_id,
            "pending",
            allowed_from=_REOPENABLE,
            now=now,
            resolved_by=resolved_by,
            reason=reason,
            mark_resolved=False,
            detail="reopened",
        )

    def close(self) -> None:
        self._conn.close()
