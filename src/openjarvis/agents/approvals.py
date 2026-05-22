"""Phase 2D — approval request store.

Append-only ``agent_approvals`` table with three states (``pending``,
``granted``, ``denied``) and timestamps for each transition. Publishes
``APPROVAL_REQUESTED`` and ``APPROVAL_RESOLVED`` on the supplied bus when
one is wired (no-op otherwise — keeps tests/CLI working).

Tool-dispatch enforcement is intentionally NOT part of this module — it
changes existing tool-call behavior and is gated behind a Change Impact
Notice. The store + routes + events shipped here let the UI and
admins exercise the approval surface end-to-end; enforcement integration
slots in via a follow-up that consults ``requires_approval_*`` axes and
creates a row through ``ApprovalStore.request()`` before the tool runs.
"""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


_CREATE = """\
CREATE TABLE IF NOT EXISTS agent_approvals (
    id TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL,
    task_id TEXT,
    capability TEXT NOT NULL,
    args_json TEXT NOT NULL DEFAULT '{}',
    summary TEXT NOT NULL DEFAULT '',
    state TEXT NOT NULL DEFAULT 'pending',
    requested_by TEXT,
    requested_at REAL NOT NULL,
    resolved_by TEXT,
    resolved_at REAL,
    decision TEXT,
    reason TEXT
);
"""


@dataclass(slots=True)
class ApprovalRequest:
    id: str
    agent_id: str
    task_id: Optional[str]
    capability: str
    args: Dict[str, Any] = field(default_factory=dict)
    summary: str = ""
    state: str = "pending"
    requested_by: Optional[str] = None
    requested_at: float = 0.0
    resolved_by: Optional[str] = None
    resolved_at: Optional[float] = None
    decision: Optional[str] = None
    reason: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "agent_id": self.agent_id,
            "task_id": self.task_id,
            "capability": self.capability,
            "args": dict(self.args),
            "summary": self.summary,
            "state": self.state,
            "requested_by": self.requested_by,
            "requested_at": self.requested_at,
            "resolved_by": self.resolved_by,
            "resolved_at": self.resolved_at,
            "decision": self.decision,
            "reason": self.reason,
        }


class ApprovalError(ValueError):
    """Raised on invalid transitions (e.g. grant of a denied approval)."""


class ApprovalStore:
    """SQLite-backed approval request store.

    The store is independent of ``AgentManager``: it owns its own
    ``agent_approvals`` table (created on demand in either its own DB
    or — recommended for production — the shared agent DB). Passing the
    same path as ``AgentManager`` colocates the rows for easy joins.
    """

    def __init__(
        self,
        db_path: str,
        event_bus: Optional[Any] = None,
    ) -> None:
        self._db_path = str(db_path)
        self._event_bus = event_bus
        self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute(_CREATE)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    # -- emission ---------------------------------------------------

    def _emit(self, event_type: Any, payload: Dict[str, Any]) -> None:
        if self._event_bus is None:
            return
        try:
            self._event_bus.publish(event_type, payload)
        except Exception:
            pass

    # -- public API -------------------------------------------------

    def request(
        self,
        agent_id: str,
        capability: str,
        args: Optional[Dict[str, Any]] = None,
        task_id: Optional[str] = None,
        summary: str = "",
        requested_by: Optional[str] = None,
    ) -> ApprovalRequest:
        """Create a new ``pending`` approval and emit ``approval.requested``."""
        approval_id = uuid.uuid4().hex[:12]
        now = time.time()
        req = ApprovalRequest(
            id=approval_id,
            agent_id=agent_id,
            task_id=task_id,
            capability=capability,
            args=dict(args or {}),
            summary=str(summary or "").strip(),
            state="pending",
            requested_by=str(requested_by or "").strip() or None,
            requested_at=now,
        )
        self._conn.execute(
            "INSERT INTO agent_approvals"
            " (id, agent_id, task_id, capability, args_json, summary,"
            " state, requested_by, requested_at)"
            " VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, ?)",
            (
                req.id,
                req.agent_id,
                req.task_id,
                req.capability,
                json.dumps(req.args),
                req.summary,
                req.requested_by,
                req.requested_at,
            ),
        )
        self._conn.commit()
        from openjarvis.core.events import EventType

        self._emit(EventType.APPROVAL_REQUESTED, req.to_dict())
        return req

    def get(self, approval_id: str) -> Optional[ApprovalRequest]:
        row = self._conn.execute(
            "SELECT * FROM agent_approvals WHERE id = ?", (approval_id,)
        ).fetchone()
        return self._row_to_request(row) if row else None

    def list(
        self,
        agent_id: Optional[str] = None,
        state: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> List[ApprovalRequest]:
        clauses: List[str] = []
        params: List[Any] = []
        if agent_id:
            clauses.append("agent_id = ?")
            params.append(agent_id)
        if state:
            clauses.append("state = ?")
            params.append(state)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        query = (
            f"SELECT * FROM agent_approvals{where}"
            " ORDER BY requested_at DESC"
        )
        if limit is not None and limit > 0:
            query += " LIMIT ?"
            params.append(int(limit))
        rows = self._conn.execute(query, params).fetchall()
        return [self._row_to_request(r) for r in rows]

    def grant(
        self,
        approval_id: str,
        resolved_by: Optional[str] = None,
        reason: Optional[str] = None,
    ) -> ApprovalRequest:
        return self._resolve(approval_id, "granted", resolved_by, reason)

    def deny(
        self,
        approval_id: str,
        resolved_by: Optional[str] = None,
        reason: Optional[str] = None,
    ) -> ApprovalRequest:
        return self._resolve(approval_id, "denied", resolved_by, reason)

    # -- internals --------------------------------------------------

    def _resolve(
        self,
        approval_id: str,
        decision: str,
        resolved_by: Optional[str],
        reason: Optional[str],
    ) -> ApprovalRequest:
        if decision not in ("granted", "denied"):
            raise ApprovalError(f"Invalid decision: {decision!r}")
        existing = self.get(approval_id)
        if existing is None:
            raise ApprovalError(f"Approval not found: {approval_id!r}")
        if existing.state != "pending":
            raise ApprovalError(
                f"Approval {approval_id!r} already {existing.state}; "
                "decisions are immutable."
            )
        now = time.time()
        new_state = decision  # 'granted' | 'denied'
        self._conn.execute(
            "UPDATE agent_approvals"
            " SET state = ?, resolved_by = ?, resolved_at = ?,"
            " decision = ?, reason = ?"
            " WHERE id = ?",
            (
                new_state,
                str(resolved_by or "").strip() or None,
                now,
                decision,
                str(reason or "").strip() or None,
                approval_id,
            ),
        )
        self._conn.commit()
        resolved = self.get(approval_id)
        assert resolved is not None
        from openjarvis.core.events import EventType

        self._emit(EventType.APPROVAL_RESOLVED, resolved.to_dict())
        return resolved

    @staticmethod
    def _row_to_request(row: sqlite3.Row) -> ApprovalRequest:
        args_raw = row["args_json"]
        return ApprovalRequest(
            id=row["id"],
            agent_id=row["agent_id"],
            task_id=row["task_id"],
            capability=row["capability"],
            args=json.loads(args_raw) if args_raw else {},
            summary=row["summary"] or "",
            state=row["state"],
            requested_by=row["requested_by"],
            requested_at=row["requested_at"],
            resolved_by=row["resolved_by"],
            resolved_at=row["resolved_at"],
            decision=row["decision"],
            reason=row["reason"],
        )
