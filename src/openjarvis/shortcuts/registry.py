"""SQLite-backed CRUD for shortcut rules.

The store lives alongside other OpenJarvis SQLite files under the user
config dir. Reads are cheap; the matcher caches the active rule list and
invalidates it on any write. Rule mutations publish ``shortcut.rule.*``
events on the shared event bus when one is provided.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from openjarvis.core.config import DEFAULT_CONFIG_DIR
from openjarvis.core.events import EventBus
from openjarvis.shortcuts._stubs import PatternSpec, ShortcutRule

_DEFAULT_DB_PATH = DEFAULT_CONFIG_DIR / "shortcuts.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS shortcut_rules (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    enabled         INTEGER NOT NULL DEFAULT 1,
    priority        INTEGER NOT NULL DEFAULT 100,
    patterns        TEXT NOT NULL,
    match_mode      TEXT NOT NULL DEFAULT 'contains',
    case_sensitive  INTEGER NOT NULL DEFAULT 0,
    target_kind     TEXT NOT NULL,
    target_id       TEXT NOT NULL,
    arg_template    TEXT NOT NULL DEFAULT '{}',
    post_prompt     TEXT,
    post_model      TEXT,
    on_failure      TEXT NOT NULL DEFAULT 'fallback_to_chief',
    failure_message TEXT,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    created_by      TEXT NOT NULL DEFAULT 'user'
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row_to_rule(row: sqlite3.Row) -> ShortcutRule:
    patterns_raw = json.loads(row["patterns"] or "[]")
    patterns = [
        PatternSpec(kind=p.get("kind", "phrase"), value=str(p.get("value", "")))
        for p in patterns_raw
        if isinstance(p, dict)
    ]
    return ShortcutRule(
        id=row["id"],
        name=row["name"],
        enabled=bool(row["enabled"]),
        priority=int(row["priority"]),
        patterns=patterns,
        match_mode=row["match_mode"],
        case_sensitive=bool(row["case_sensitive"]),
        target_kind=row["target_kind"],
        target_id=row["target_id"],
        arg_template=json.loads(row["arg_template"] or "{}"),
        post_prompt=row["post_prompt"],
        post_model=row["post_model"],
        on_failure=row["on_failure"],
        failure_message=row["failure_message"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        created_by=row["created_by"],
    )


def _rule_to_params(rule: ShortcutRule) -> Dict[str, Any]:
    return {
        "id": rule.id,
        "name": rule.name,
        "enabled": 1 if rule.enabled else 0,
        "priority": rule.priority,
        "patterns": json.dumps([asdict(p) for p in rule.patterns]),
        "match_mode": rule.match_mode,
        "case_sensitive": 1 if rule.case_sensitive else 0,
        "target_kind": rule.target_kind,
        "target_id": rule.target_id,
        "arg_template": json.dumps(rule.arg_template),
        "post_prompt": rule.post_prompt,
        "post_model": rule.post_model,
        "on_failure": rule.on_failure,
        "failure_message": rule.failure_message,
        "created_at": rule.created_at or _now(),
        "updated_at": _now(),
        "created_by": rule.created_by,
    }


class ShortcutRegistry:
    """Thread-safe CRUD over the ``shortcut_rules`` table."""

    def __init__(
        self,
        db_path: Optional[Path] = None,
        bus: Optional[EventBus] = None,
    ) -> None:
        self._path = Path(db_path) if db_path else _DEFAULT_DB_PATH
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._bus = bus
        self._lock = threading.RLock()
        self._cache: Optional[List[ShortcutRule]] = None
        with self._connect() as conn:
            conn.executescript(_SCHEMA)
            conn.commit()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._path))
        conn.row_factory = sqlite3.Row
        return conn

    def _invalidate(self) -> None:
        self._cache = None

    def _publish(self, event_name: str, payload: Dict[str, Any]) -> None:
        if self._bus is None:
            return
        try:
            self._bus.publish(event_name, payload)
        except Exception:
            # Event publishing must never break a write.
            pass

    def list(self, *, include_disabled: bool = True) -> List[ShortcutRule]:
        with self._lock:
            if self._cache is None:
                with self._connect() as conn:
                    rows = conn.execute(
                        "SELECT * FROM shortcut_rules"
                        " ORDER BY priority DESC, updated_at DESC"
                    ).fetchall()
                self._cache = [_row_to_rule(r) for r in rows]
            if include_disabled:
                return list(self._cache)
            return [r for r in self._cache if r.enabled]

    def get(self, rule_id: str) -> Optional[ShortcutRule]:
        for rule in self.list():
            if rule.id == rule_id:
                return rule
        return None

    def upsert(self, rule: ShortcutRule) -> ShortcutRule:
        with self._lock:
            if not rule.id:
                rule.id = str(uuid.uuid4())
            params = _rule_to_params(rule)
            # Mirror the values _rule_to_params synthesised back onto the
            # input so the returned object matches the persisted row
            # (callers commonly serialise the return value).
            rule.created_at = params["created_at"]
            rule.updated_at = params["updated_at"]
            existed = self.get(rule.id) is not None
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO shortcut_rules (
                        id, name, enabled, priority, patterns, match_mode,
                        case_sensitive, target_kind, target_id, arg_template,
                        post_prompt, post_model, on_failure, failure_message,
                        created_at, updated_at, created_by
                    ) VALUES (
                        :id, :name, :enabled, :priority, :patterns, :match_mode,
                        :case_sensitive, :target_kind, :target_id, :arg_template,
                        :post_prompt, :post_model, :on_failure, :failure_message,
                        :created_at, :updated_at, :created_by
                    )
                    ON CONFLICT(id) DO UPDATE SET
                        name=excluded.name,
                        enabled=excluded.enabled,
                        priority=excluded.priority,
                        patterns=excluded.patterns,
                        match_mode=excluded.match_mode,
                        case_sensitive=excluded.case_sensitive,
                        target_kind=excluded.target_kind,
                        target_id=excluded.target_id,
                        arg_template=excluded.arg_template,
                        post_prompt=excluded.post_prompt,
                        post_model=excluded.post_model,
                        on_failure=excluded.on_failure,
                        failure_message=excluded.failure_message,
                        updated_at=excluded.updated_at
                    """,
                    params,
                )
                conn.commit()
            self._invalidate()
            self._publish(
                "shortcut.rule.updated" if existed else "shortcut.rule.created",
                {"rule_id": rule.id, "name": rule.name},
            )
            return rule

    def delete(self, rule_id: str) -> bool:
        with self._lock:
            with self._connect() as conn:
                cur = conn.execute(
                    "DELETE FROM shortcut_rules WHERE id = ?",
                    (rule_id,),
                )
                conn.commit()
                deleted = cur.rowcount > 0
            if deleted:
                self._invalidate()
                self._publish("shortcut.rule.deleted", {"rule_id": rule_id})
            return deleted

    def reload(self) -> None:
        with self._lock:
            self._invalidate()


__all__ = ["ShortcutRegistry"]
