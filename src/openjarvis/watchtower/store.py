"""SQLite persistence for Jarvis Watchtower."""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from openjarvis.core.config import DEFAULT_CONFIG_DIR
from openjarvis.watchtower.types import InternalRoute, Priority, WatchtowerFinding

_SCHEMA = """
CREATE TABLE IF NOT EXISTS watchtower_findings (
    finding_id TEXT PRIMARY KEY,
    finding_type TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    project_id TEXT,
    task_id TEXT,
    agent_id TEXT,
    priority TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    reason TEXT NOT NULL DEFAULT '',
    recommended_action TEXT NOT NULL DEFAULT '',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    resolved_at REAL,
    last_notified_at REAL,
    notification_count INTEGER NOT NULL DEFAULT 0,
    dedupe_key TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}'
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_watchtower_findings_dedupe_active
ON watchtower_findings(dedupe_key)
WHERE status IN ('active', 'snoozed');

CREATE TABLE IF NOT EXISTS watchtower_notifications (
    notification_id TEXT PRIMARY KEY,
    finding_id TEXT NOT NULL,
    priority TEXT NOT NULL,
    route TEXT NOT NULL,
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    decision TEXT NOT NULL,
    dnd_applied INTEGER NOT NULL DEFAULT 0,
    bypassed_dnd INTEGER NOT NULL DEFAULT 0,
    sent_at REAL,
    error_message TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS watchtower_speech_events (
    speech_event_id TEXT PRIMARY KEY,
    finding_id TEXT NOT NULL,
    priority TEXT NOT NULL,
    text_spoken TEXT NOT NULL,
    dnd_applied INTEGER NOT NULL DEFAULT 0,
    bypassed_dnd INTEGER NOT NULL DEFAULT 0,
    spoken_at REAL,
    success INTEGER NOT NULL DEFAULT 0,
    error_message TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS watchtower_internal_routes (
    route_id TEXT PRIMARY KEY,
    finding_id TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'watchtower',
    from_agent_id TEXT NOT NULL DEFAULT 'watchtower',
    to_agent_id TEXT NOT NULL,
    route_type TEXT NOT NULL,
    priority TEXT NOT NULL,
    message_type TEXT NOT NULL,
    requires_response INTEGER NOT NULL DEFAULT 1,
    response_due_at REAL,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at REAL NOT NULL,
    responded_at REAL,
    escalated_at REAL,
    metadata_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS watchtower_escalations (
    escalation_id TEXT PRIMARY KEY,
    finding_id TEXT NOT NULL,
    route_id TEXT,
    escalation_reason TEXT NOT NULL DEFAULT '',
    user_notified INTEGER NOT NULL DEFAULT 0,
    notification_id TEXT,
    created_at REAL NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS watchtower_settings (
    setting_name TEXT PRIMARY KEY,
    setting_value TEXT NOT NULL,
    data_type TEXT NOT NULL DEFAULT 'str',
    updated_at REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_watchtower_findings_status
ON watchtower_findings(status, priority);

CREATE INDEX IF NOT EXISTS idx_watchtower_routes_status
ON watchtower_internal_routes(status, priority);

CREATE INDEX IF NOT EXISTS idx_watchtower_speech_finding
ON watchtower_speech_events(finding_id, spoken_at);
"""


def default_db_path() -> Path:
    return DEFAULT_CONFIG_DIR / "watchtower.db"


def _now() -> float:
    return time.time()


def _id(prefix: str = "") -> str:
    return f"{prefix}{uuid.uuid4().hex[:12]}"


def _json(data: Any) -> str:
    try:
        return json.dumps(data or {}, sort_keys=True)
    except Exception:
        return "{}"


def _parse_json(raw: Any) -> Dict[str, Any]:
    try:
        value = json.loads(raw or "{}")
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


class WatchtowerStore:
    def __init__(self, db_path: str | Path | None = None) -> None:
        self._path = Path(db_path) if db_path else default_db_path()
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def upsert_finding(
        self,
        *,
        finding_type: str,
        entity_type: str,
        entity_id: str,
        priority: Priority | str,
        reason: str,
        recommended_action: str = "",
        project_id: str | None = None,
        task_id: str | None = None,
        agent_id: str | None = None,
        dedupe_key: str | None = None,
        metadata: Dict[str, Any] | None = None,
    ) -> WatchtowerFinding:
        pri = priority if isinstance(priority, Priority) else Priority(str(priority))
        key = dedupe_key or f"{finding_type}:{entity_type}:{entity_id}:{pri.value}"
        existing = self._conn.execute(
            "SELECT * FROM watchtower_findings"
            " WHERE dedupe_key = ? AND status IN ('active', 'snoozed')",
            (key,),
        ).fetchone()
        now = _now()
        if existing:
            self._conn.execute(
                "UPDATE watchtower_findings SET priority = ?, reason = ?,"
                " recommended_action = ?, updated_at = ?, metadata_json = ?"
                " WHERE finding_id = ?",
                (
                    pri.value,
                    reason,
                    recommended_action,
                    now,
                    _json(metadata),
                    existing["finding_id"],
                ),
            )
            self._conn.commit()
            return self.get_finding(existing["finding_id"])  # type: ignore[return-value]

        finding_id = _id("wf_")
        self._conn.execute(
            "INSERT INTO watchtower_findings"
            " (finding_id, finding_type, entity_type, entity_id, project_id,"
            " task_id, agent_id, priority, status, reason, recommended_action,"
            " created_at, updated_at, dedupe_key, metadata_json)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?, ?, ?, ?, ?)",
            (
                finding_id,
                finding_type,
                entity_type,
                entity_id,
                project_id,
                task_id,
                agent_id,
                pri.value,
                reason,
                recommended_action,
                now,
                now,
                key,
                _json(metadata),
            ),
        )
        self._conn.commit()
        return self.get_finding(finding_id)  # type: ignore[return-value]

    def get_finding(self, finding_id: str) -> Optional[WatchtowerFinding]:
        row = self._conn.execute(
            "SELECT * FROM watchtower_findings WHERE finding_id = ?",
            (finding_id,),
        ).fetchone()
        return self._row_to_finding(row) if row else None

    def list_findings(
        self,
        *,
        status: str | None = None,
        priority: str | None = None,
        limit: int = 100,
    ) -> List[WatchtowerFinding]:
        clauses: list[str] = []
        params: list[Any] = []
        if status:
            clauses.append("status = ?")
            params.append(status)
        if priority:
            clauses.append("priority = ?")
            params.append(priority)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self._conn.execute(
            f"SELECT * FROM watchtower_findings{where}"
            " ORDER BY updated_at DESC LIMIT ?",
            (*params, int(limit)),
        ).fetchall()
        return [self._row_to_finding(row) for row in rows]

    def update_finding_status(self, finding_id: str, status: str) -> WatchtowerFinding:
        now = _now()
        resolved = now if status == "resolved" else None
        self._conn.execute(
            "UPDATE watchtower_findings SET status = ?, updated_at = ?,"
            " resolved_at = COALESCE(?, resolved_at) WHERE finding_id = ?",
            (status, now, resolved, finding_id),
        )
        self._conn.commit()
        found = self.get_finding(finding_id)
        if found is None:
            raise KeyError(finding_id)
        return found

    def record_notification(
        self,
        *,
        finding_id: str,
        priority: Priority | str,
        route: str,
        title: str,
        body: str,
        decision: str,
        dnd_applied: bool = False,
        bypassed_dnd: bool = False,
        error_message: str | None = None,
        metadata: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        now = _now()
        notification_id = _id("wn_")
        sent_at = now if decision == "sent" else None
        pri = priority if isinstance(priority, Priority) else Priority(str(priority))
        self._conn.execute(
            "INSERT INTO watchtower_notifications"
            " (notification_id, finding_id, priority, route, title, body,"
            " decision, dnd_applied, bypassed_dnd, sent_at, error_message,"
            " metadata_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                notification_id,
                finding_id,
                pri.value,
                route,
                title,
                body,
                decision,
                1 if dnd_applied else 0,
                1 if bypassed_dnd else 0,
                sent_at,
                error_message,
                _json(metadata),
            ),
        )
        if sent_at:
            self._conn.execute(
                "UPDATE watchtower_findings SET last_notified_at = ?,"
                " notification_count = notification_count + 1"
                " WHERE finding_id = ?",
                (sent_at, finding_id),
            )
        self._conn.commit()
        return {
            "notification_id": notification_id,
            "finding_id": finding_id,
            "priority": pri.value,
            "route": route,
            "title": title,
            "body": body,
            "decision": decision,
            "dnd_applied": dnd_applied,
            "bypassed_dnd": bypassed_dnd,
            "sent_at": sent_at,
            "error_message": error_message,
            "metadata": metadata or {},
        }

    def create_internal_route(
        self,
        *,
        finding_id: str,
        to_agent_id: str,
        route_type: str,
        priority: Priority | str,
        message_type: str,
        from_agent_id: str = "watchtower",
        source: str = "watchtower",
        requires_response: bool = True,
        response_due_at: float | None = None,
        status: str = "pending",
        metadata: Dict[str, Any] | None = None,
    ) -> InternalRoute:
        route_id = _id("wr_")
        pri = priority if isinstance(priority, Priority) else Priority(str(priority))
        now = _now()
        self._conn.execute(
            "INSERT INTO watchtower_internal_routes"
            " (route_id, finding_id, source, from_agent_id, to_agent_id,"
            " route_type, priority, message_type, requires_response,"
            " response_due_at, status, created_at, metadata_json)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                route_id,
                finding_id,
                source,
                from_agent_id,
                to_agent_id,
                route_type,
                pri.value,
                message_type,
                1 if requires_response else 0,
                response_due_at,
                status,
                now,
                _json(metadata),
            ),
        )
        self._conn.commit()
        return self.get_internal_route(route_id)  # type: ignore[return-value]

    def get_recent_internal_route(
        self,
        *,
        finding_id: str,
        route_type: str,
        to_agent_id: str,
        cooldown_seconds: float,
        statuses: tuple[str, ...] = ("pending", "sent"),
    ) -> Optional[InternalRoute]:
        placeholders = ", ".join("?" for _ in statuses)
        cutoff = _now() - cooldown_seconds
        row = self._conn.execute(
            "SELECT * FROM watchtower_internal_routes"
            " WHERE finding_id = ? AND route_type = ? AND to_agent_id = ?"
            f" AND status IN ({placeholders}) AND created_at >= ?"
            " ORDER BY created_at DESC LIMIT 1",
            (finding_id, route_type, to_agent_id, *statuses, cutoff),
        ).fetchone()
        return self._row_to_route(row) if row else None

    def get_internal_route(self, route_id: str) -> Optional[InternalRoute]:
        row = self._conn.execute(
            "SELECT * FROM watchtower_internal_routes WHERE route_id = ?",
            (route_id,),
        ).fetchone()
        return self._row_to_route(row) if row else None

    def list_internal_routes(
        self,
        *,
        status: str | None = None,
        limit: int = 100,
    ) -> List[InternalRoute]:
        params: list[Any] = []
        where = ""
        if status:
            where = " WHERE status = ?"
            params.append(status)
        rows = self._conn.execute(
            f"SELECT * FROM watchtower_internal_routes{where}"
            " ORDER BY created_at DESC LIMIT ?",
            (*params, int(limit)),
        ).fetchall()
        return [self._row_to_route(row) for row in rows]

    def list_notifications(
        self,
        *,
        finding_id: str | None = None,
        decision: str | None = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if finding_id:
            clauses.append("finding_id = ?")
            params.append(finding_id)
        if decision:
            clauses.append("decision = ?")
            params.append(decision)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self._conn.execute(
            f"SELECT * FROM watchtower_notifications{where}"
            " ORDER BY COALESCE(sent_at, rowid) DESC LIMIT ?",
            (*params, int(limit)),
        ).fetchall()
        return [
            {
                "notification_id": row["notification_id"],
                "finding_id": row["finding_id"],
                "priority": row["priority"],
                "route": row["route"],
                "title": row["title"],
                "body": row["body"],
                "decision": row["decision"],
                "dnd_applied": bool(row["dnd_applied"]),
                "bypassed_dnd": bool(row["bypassed_dnd"]),
                "sent_at": row["sent_at"],
                "error_message": row["error_message"],
                "metadata": _parse_json(row["metadata_json"]),
            }
            for row in rows
        ]

    def record_speech_event(
        self,
        *,
        finding_id: str,
        priority: Priority | str,
        text_spoken: str,
        success: bool,
        dnd_applied: bool = False,
        bypassed_dnd: bool = False,
        error_message: str | None = None,
        metadata: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        now = _now()
        speech_event_id = _id("ws_")
        pri = priority if isinstance(priority, Priority) else Priority(str(priority))
        spoken_at = now if success else None
        self._conn.execute(
            "INSERT INTO watchtower_speech_events"
            " (speech_event_id, finding_id, priority, text_spoken,"
            " dnd_applied, bypassed_dnd, spoken_at, success, error_message,"
            " metadata_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                speech_event_id,
                finding_id,
                pri.value,
                text_spoken,
                1 if dnd_applied else 0,
                1 if bypassed_dnd else 0,
                spoken_at,
                1 if success else 0,
                error_message,
                _json(metadata),
            ),
        )
        self._conn.commit()
        return {
            "speech_event_id": speech_event_id,
            "finding_id": finding_id,
            "priority": pri.value,
            "text_spoken": text_spoken,
            "dnd_applied": dnd_applied,
            "bypassed_dnd": bypassed_dnd,
            "spoken_at": spoken_at,
            "success": success,
            "error_message": error_message,
            "metadata": metadata or {},
        }

    def list_speech_events(
        self,
        *,
        finding_id: str | None = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        params: list[Any] = []
        where = ""
        if finding_id:
            where = " WHERE finding_id = ?"
            params.append(finding_id)
        rows = self._conn.execute(
            f"SELECT * FROM watchtower_speech_events{where}"
            " ORDER BY COALESCE(spoken_at, rowid) DESC LIMIT ?",
            (*params, int(limit)),
        ).fetchall()
        return [
            {
                "speech_event_id": row["speech_event_id"],
                "finding_id": row["finding_id"],
                "priority": row["priority"],
                "text_spoken": row["text_spoken"],
                "dnd_applied": bool(row["dnd_applied"]),
                "bypassed_dnd": bool(row["bypassed_dnd"]),
                "spoken_at": row["spoken_at"],
                "success": bool(row["success"]),
                "error_message": row["error_message"],
                "metadata": _parse_json(row["metadata_json"]),
            }
            for row in rows
        ]

    def list_overdue_internal_routes(
        self,
        *,
        now_ts: float,
        limit: int = 100,
    ) -> List[InternalRoute]:
        rows = self._conn.execute(
            "SELECT * FROM watchtower_internal_routes"
            " WHERE status = 'sent' AND requires_response = 1"
            " AND response_due_at IS NOT NULL AND response_due_at <= ?"
            " ORDER BY response_due_at ASC LIMIT ?",
            (now_ts, int(limit)),
        ).fetchall()
        return [self._row_to_route(row) for row in rows]

    def update_internal_route_status(self, route_id: str, status: str) -> InternalRoute:
        now = _now()
        responded = now if status in {"responded", "resolved"} else None
        escalated = now if status == "escalated" else None
        self._conn.execute(
            "UPDATE watchtower_internal_routes SET status = ?,"
            " responded_at = COALESCE(?, responded_at),"
            " escalated_at = COALESCE(?, escalated_at)"
            " WHERE route_id = ?",
            (status, responded, escalated, route_id),
        )
        self._conn.commit()
        route = self.get_internal_route(route_id)
        if route is None:
            raise KeyError(route_id)
        return route

    def record_escalation(
        self,
        *,
        finding_id: str,
        escalation_reason: str,
        route_id: str | None = None,
        user_notified: bool = False,
        notification_id: str | None = None,
        metadata: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        escalation_id = _id("we_")
        now = _now()
        self._conn.execute(
            "INSERT INTO watchtower_escalations"
            " (escalation_id, finding_id, route_id, escalation_reason,"
            " user_notified, notification_id, created_at, metadata_json)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                escalation_id,
                finding_id,
                route_id,
                escalation_reason,
                1 if user_notified else 0,
                notification_id,
                now,
                _json(metadata),
            ),
        )
        self._conn.commit()
        return {
            "escalation_id": escalation_id,
            "finding_id": finding_id,
            "route_id": route_id,
            "escalation_reason": escalation_reason,
            "user_notified": user_notified,
            "notification_id": notification_id,
            "created_at": now,
            "metadata": metadata or {},
        }

    def get_settings(self) -> Dict[str, Any]:
        rows = self._conn.execute("SELECT * FROM watchtower_settings").fetchall()
        return {
            row["setting_name"]: self._decode_setting(
                row["setting_value"], row["data_type"]
            )
            for row in rows
        }

    def patch_settings(self, updates: Dict[str, Any]) -> Dict[str, Any]:
        now = _now()
        for key, value in updates.items():
            dtype, encoded = self._encode_setting(value)
            self._conn.execute(
                "INSERT INTO watchtower_settings"
                " (setting_name, setting_value, data_type, updated_at)"
                " VALUES (?, ?, ?, ?)"
                " ON CONFLICT(setting_name) DO UPDATE SET"
                " setting_value = excluded.setting_value,"
                " data_type = excluded.data_type,"
                " updated_at = excluded.updated_at",
                (str(key), encoded, dtype, now),
            )
        self._conn.commit()
        return self.get_settings()

    def _row_to_finding(self, row: sqlite3.Row) -> WatchtowerFinding:
        return WatchtowerFinding(
            finding_id=row["finding_id"],
            finding_type=row["finding_type"],
            entity_type=row["entity_type"],
            entity_id=row["entity_id"],
            project_id=row["project_id"],
            task_id=row["task_id"],
            agent_id=row["agent_id"],
            priority=Priority(row["priority"]),
            status=row["status"],
            reason=row["reason"],
            recommended_action=row["recommended_action"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            resolved_at=row["resolved_at"],
            last_notified_at=row["last_notified_at"],
            notification_count=int(row["notification_count"] or 0),
            dedupe_key=row["dedupe_key"],
            metadata=_parse_json(row["metadata_json"]),
        )

    def _row_to_route(self, row: sqlite3.Row) -> InternalRoute:
        return InternalRoute(
            route_id=row["route_id"],
            finding_id=row["finding_id"],
            source=row["source"],
            from_agent_id=row["from_agent_id"],
            to_agent_id=row["to_agent_id"],
            route_type=row["route_type"],
            priority=Priority(row["priority"]),
            message_type=row["message_type"],
            requires_response=bool(row["requires_response"]),
            response_due_at=row["response_due_at"],
            status=row["status"],
            created_at=row["created_at"],
            responded_at=row["responded_at"],
            escalated_at=row["escalated_at"],
            metadata=_parse_json(row["metadata_json"]),
        )

    @staticmethod
    def _encode_setting(value: Any) -> tuple[str, str]:
        if isinstance(value, bool):
            return "bool", "true" if value else "false"
        if isinstance(value, int):
            return "int", str(value)
        if isinstance(value, float):
            return "float", str(value)
        if isinstance(value, (dict, list)):
            return "json", json.dumps(value)
        return "str", str(value)

    @staticmethod
    def _decode_setting(value: str, dtype: str) -> Any:
        if dtype == "bool":
            return str(value).lower() == "true"
        if dtype == "int":
            return int(value)
        if dtype == "float":
            return float(value)
        if dtype == "json":
            return json.loads(value)
        return value
