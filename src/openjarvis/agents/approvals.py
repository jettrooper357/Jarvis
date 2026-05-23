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

import hashlib
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
    args_hash TEXT,
    summary TEXT NOT NULL DEFAULT '',
    state TEXT NOT NULL DEFAULT 'pending',
    requested_by TEXT,
    requested_at REAL NOT NULL,
    resolved_by TEXT,
    resolved_at REAL,
    consumed_at REAL,
    decision TEXT,
    reason TEXT
);
"""

# Columns added after the Phase-2D table first shipped. Applied to
# pre-existing databases via ``ALTER TABLE`` on connect (additive,
# nullable — safe to leave when approval gating is off).
_ADDED_COLUMNS = (
    ("args_hash", "TEXT"),
    ("consumed_at", "REAL"),
)


def normalize_args(args: Any) -> str:
    """Canonicalise tool arguments so trivially-different forms match.

    Accepts a JSON string or a mapping; returns a stable JSON string
    with sorted keys. Non-JSON strings fall back to a trimmed form.
    """
    if isinstance(args, str):
        try:
            parsed: Any = json.loads(args)
        except Exception:
            return args.strip()
    else:
        parsed = args
    try:
        return json.dumps(parsed, sort_keys=True, separators=(",", ":"))
    except Exception:
        return str(parsed).strip()


def args_hash(args: Any) -> str:
    """Stable SHA-256 of the normalized tool arguments.

    Used to scope a granted approval to one specific invocation: an
    approval of ``delete_files(/tmp/x)`` will not authorize
    ``delete_files(/etc)``.
    """
    return hashlib.sha256(normalize_args(args).encode("utf-8")).hexdigest()


# Private alias so ``ApprovalStore.request`` can compute a hash even
# though its ``args_hash`` parameter shadows the public function name.
_compute_args_hash = args_hash


@dataclass(slots=True)
class ApprovalRequest:
    id: str
    agent_id: str
    task_id: Optional[str]
    capability: str
    args: Dict[str, Any] = field(default_factory=dict)
    args_hash: Optional[str] = None
    summary: str = ""
    state: str = "pending"
    requested_by: Optional[str] = None
    requested_at: float = 0.0
    resolved_by: Optional[str] = None
    resolved_at: Optional[float] = None
    consumed_at: Optional[float] = None
    decision: Optional[str] = None
    reason: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "agent_id": self.agent_id,
            "task_id": self.task_id,
            "capability": self.capability,
            "args": dict(self.args),
            "args_hash": self.args_hash,
            "summary": self.summary,
            "state": self.state,
            "requested_by": self.requested_by,
            "requested_at": self.requested_at,
            "resolved_by": self.resolved_by,
            "resolved_at": self.resolved_at,
            "consumed_at": self.consumed_at,
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
        self._ensure_columns()
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def _ensure_columns(self) -> None:
        """Additively migrate pre-existing ``agent_approvals`` tables."""
        existing = {
            row["name"]
            for row in self._conn.execute(
                "PRAGMA table_info(agent_approvals)"
            ).fetchall()
        }
        for name, decl in _ADDED_COLUMNS:
            if name not in existing:
                self._conn.execute(
                    f"ALTER TABLE agent_approvals ADD COLUMN {name} {decl}"
                )

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
        args_hash: Optional[str] = None,
    ) -> ApprovalRequest:
        """Create a new ``pending`` approval and emit ``approval.requested``.

        ``args_hash`` scopes a future grant to this exact invocation; when
        omitted it is derived from ``args``.
        """
        approval_id = uuid.uuid4().hex[:12]
        now = time.time()
        args_dict = dict(args or {})
        req = ApprovalRequest(
            id=approval_id,
            agent_id=agent_id,
            task_id=task_id,
            capability=capability,
            args=args_dict,
            args_hash=(
                str(args_hash)
                if args_hash
                else _compute_args_hash(args_dict)
            ),
            summary=str(summary or "").strip(),
            state="pending",
            requested_by=str(requested_by or "").strip() or None,
            requested_at=now,
        )
        self._conn.execute(
            "INSERT INTO agent_approvals"
            " (id, agent_id, task_id, capability, args_json, args_hash,"
            " summary, state, requested_by, requested_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?)",
            (
                req.id,
                req.agent_id,
                req.task_id,
                req.capability,
                json.dumps(req.args),
                req.args_hash,
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
        require_human_grant: bool = True,
    ) -> ApprovalRequest:
        """Grant a pending approval.

        When ``require_human_grant`` is True (default), a grant whose
        ``resolved_by`` is the requesting agent itself is rejected — an
        agent must not approve its own pending request.
        """
        return self._resolve(
            approval_id,
            "granted",
            resolved_by,
            reason,
            require_human_grant=require_human_grant,
        )

    def deny(
        self,
        approval_id: str,
        resolved_by: Optional[str] = None,
        reason: Optional[str] = None,
    ) -> ApprovalRequest:
        return self._resolve(approval_id, "denied", resolved_by, reason)

    def find_actionable(
        self,
        agent_id: str,
        capability: str,
        args_hash: str,
    ) -> Optional[ApprovalRequest]:
        """Return the newest resolution that decides this exact call.

        Matches the ``(agent_id, capability, args_hash)`` triple and
        returns the most recent unconsumed ``granted`` or any ``denied``
        approval, or ``None`` when no human decision exists yet.
        """
        row = self._conn.execute(
            "SELECT * FROM agent_approvals"
            " WHERE agent_id = ? AND capability = ? AND args_hash = ?"
            " AND ((state = 'granted' AND consumed_at IS NULL)"
            "      OR state = 'denied')"
            " ORDER BY requested_at DESC LIMIT 1",
            (agent_id, capability, args_hash),
        ).fetchone()
        return self._row_to_request(row) if row else None

    def mark_consumed(self, approval_id: str) -> None:
        """Mark a granted approval as spent — it can authorize no further call."""
        self._conn.execute(
            "UPDATE agent_approvals SET consumed_at = ? WHERE id = ?",
            (time.time(), approval_id),
        )
        self._conn.commit()

    # -- internals --------------------------------------------------

    def _resolve(
        self,
        approval_id: str,
        decision: str,
        resolved_by: Optional[str],
        reason: Optional[str],
        *,
        require_human_grant: bool = False,
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
        if (
            decision == "granted"
            and require_human_grant
            and resolved_by
            and str(resolved_by).strip() == str(existing.agent_id).strip()
        ):
            raise ApprovalError(
                f"Approval {approval_id!r} cannot be granted by the "
                "requesting agent itself — a human must grant it."
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
        keys = row.keys()
        return ApprovalRequest(
            id=row["id"],
            agent_id=row["agent_id"],
            task_id=row["task_id"],
            capability=row["capability"],
            args=json.loads(args_raw) if args_raw else {},
            args_hash=row["args_hash"] if "args_hash" in keys else None,
            summary=row["summary"] or "",
            state=row["state"],
            requested_by=row["requested_by"],
            requested_at=row["requested_at"],
            resolved_by=row["resolved_by"],
            resolved_at=row["resolved_at"],
            consumed_at=row["consumed_at"] if "consumed_at" in keys else None,
            decision=row["decision"],
            reason=row["reason"],
        )
