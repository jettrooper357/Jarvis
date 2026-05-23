"""Persistent agent lifecycle manager.

Composition layer — stores agent state in SQLite, delegates all computation
to the five existing primitives (Intelligence, Agent, Tools, Engine, Learning).
"""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from uuid import uuid4

_CREATE_AGENTS = """\
CREATE TABLE IF NOT EXISTS managed_agents (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    agent_type      TEXT NOT NULL DEFAULT 'monitor_operative',
    org_role        TEXT NOT NULL DEFAULT '',
    manager_agent_id TEXT REFERENCES managed_agents(id),
    config_json     TEXT NOT NULL DEFAULT '{}',
    status          TEXT NOT NULL DEFAULT 'idle',
    summary_memory  TEXT NOT NULL DEFAULT '',
    avatar_url      TEXT,
    avatar_mime_type TEXT,
    avatar_file_name TEXT,
    avatar_updated_at REAL,
    created_at      REAL NOT NULL,
    updated_at      REAL NOT NULL
);
"""

_CREATE_TASKS = """\
CREATE TABLE IF NOT EXISTS agent_tasks (
    id              TEXT PRIMARY KEY,
    agent_id        TEXT NOT NULL REFERENCES managed_agents(id),
    assigned_by_agent_id TEXT REFERENCES managed_agents(id),
    description     TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'pending',
    progress_json   TEXT NOT NULL DEFAULT '{}',
    findings_json   TEXT NOT NULL DEFAULT '[]',
    created_at      REAL NOT NULL
);
"""

_CREATE_BINDINGS = """\
CREATE TABLE IF NOT EXISTS channel_bindings (
    id              TEXT PRIMARY KEY,
    agent_id        TEXT NOT NULL REFERENCES managed_agents(id),
    channel_type    TEXT NOT NULL,
    config_json     TEXT NOT NULL DEFAULT '{}',
    session_id      TEXT,
    routing_mode    TEXT NOT NULL DEFAULT 'dedicated'
);
"""

_CREATE_CHECKPOINTS = """\
CREATE TABLE IF NOT EXISTS agent_checkpoints (
    id TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL REFERENCES managed_agents(id),
    tick_id TEXT NOT NULL,
    conversation_state TEXT NOT NULL DEFAULT '{}',
    tool_state TEXT NOT NULL DEFAULT '{}',
    created_at REAL NOT NULL
);
"""

_CREATE_MESSAGES = """\
CREATE TABLE IF NOT EXISTS agent_messages (
    id TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL REFERENCES managed_agents(id),
    direction TEXT NOT NULL,
    content TEXT NOT NULL,
    mode TEXT NOT NULL DEFAULT 'queued',
    status TEXT NOT NULL DEFAULT 'pending',
    created_at REAL NOT NULL
);
"""

_CREATE_LEARNING_LOG = """\
CREATE TABLE IF NOT EXISTS agent_learning_log (
    id TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    description TEXT,
    data TEXT,
    created_at REAL NOT NULL
);
"""

# Phase 2A: append-only history of agent config snapshots. Written by
# update_agent whenever the config blob actually changes; never updated
# in place (revert appends a new row with the older snapshot).
_CREATE_CONFIG_VERSIONS = """\
CREATE TABLE IF NOT EXISTS agent_config_versions (
    id TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL REFERENCES managed_agents(id),
    version_number INTEGER NOT NULL,
    snapshot_json TEXT NOT NULL,
    diff_json TEXT NOT NULL DEFAULT '{}',
    summary TEXT NOT NULL DEFAULT '',
    created_at REAL NOT NULL,
    created_by TEXT
);
"""

_SUMMARY_MAX = 2000

# System project that holds agent work not yet tied to a real project task.
# Created on demand by the migration backfill; surfaced in Mission Control
# as "needs reconciliation".
_UNASSIGNED_PROJECT_NAME = "Unassigned Work"


def _worker_session_isolation_enabled() -> bool:
    """Phase 2G — lazy read of the worker-session-isolation feature flag.

    Falls back to False (today's behaviour) on any config-loader error
    so a missing or malformed config never alters message-listing
    semantics by accident.
    """
    try:
        from openjarvis.core.config import load_config

        return bool(load_config().worker_session_isolation.enabled)
    except Exception:
        return False


def _default_agent_project_task_dates() -> Dict[str, str]:
    start = datetime.now().date()
    return {
        "start_date": start.isoformat(),
        "due_date": (start + timedelta(days=1)).isoformat(),
    }


class AgentManager:
    """Persistent agent lifecycle manager with SQLite backing."""

    def __init__(
        self,
        db_path: str,
        project_store: Optional[Any] = None,
        event_bus: Optional[Any] = None,
    ) -> None:
        self._db_path = str(db_path)
        # Lazily-resolved ProjectStore for cross-store linkage validation /
        # backfill. Injectable so tests can isolate the projects DB.
        self._injected_project_store = project_store
        self._proj_store: Optional[Any] = project_store
        # Phase 2C — optional EventBus for task.* lifecycle emission.
        # Default None preserves existing test/CLI callers; production
        # callsites (cli/serve.py, system/builder.py) pass the shared bus.
        self._event_bus = event_bus
        self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.execute(_CREATE_AGENTS)
        self._conn.execute(_CREATE_TASKS)
        self._conn.execute(_CREATE_BINDINGS)
        self._conn.executescript(_CREATE_CHECKPOINTS)
        self._conn.executescript(_CREATE_MESSAGES)
        self._conn.executescript(_CREATE_LEARNING_LOG)
        self._conn.executescript(_CREATE_CONFIG_VERSIONS)
        self._conn.commit()
        # Schema migrations for runtime columns
        _MIGRATIONS = [
            "ALTER TABLE managed_agents ADD COLUMN org_role TEXT NOT NULL DEFAULT ''",
            "ALTER TABLE managed_agents ADD COLUMN manager_agent_id TEXT",
            "ALTER TABLE managed_agents ADD COLUMN total_tokens INTEGER DEFAULT 0",
            "ALTER TABLE managed_agents ADD COLUMN total_cost REAL DEFAULT 0",
            "ALTER TABLE managed_agents ADD COLUMN total_runs INTEGER DEFAULT 0",
            "ALTER TABLE managed_agents ADD COLUMN last_run_at REAL",
            "ALTER TABLE managed_agents ADD COLUMN last_activity_at REAL",
            "ALTER TABLE managed_agents ADD COLUMN stall_retries INTEGER DEFAULT 0",
            "ALTER TABLE managed_agents ADD COLUMN current_activity TEXT DEFAULT ''",
            "ALTER TABLE managed_agents ADD COLUMN input_tokens INTEGER DEFAULT 0",
            "ALTER TABLE managed_agents ADD COLUMN output_tokens INTEGER DEFAULT 0",
            "ALTER TABLE managed_agents ADD COLUMN avatar_url TEXT",
            "ALTER TABLE managed_agents ADD COLUMN avatar_mime_type TEXT",
            "ALTER TABLE managed_agents ADD COLUMN avatar_file_name TEXT",
            "ALTER TABLE managed_agents ADD COLUMN avatar_updated_at REAL",
            "ALTER TABLE agent_tasks ADD COLUMN assigned_by_agent_id TEXT",
            # JSON-encoded array of {tool, arguments, result, success, latency}
            "ALTER TABLE agent_messages ADD COLUMN tool_calls TEXT",
            # Mission Control: every agent task links to a project task/subtask
            "ALTER TABLE agent_tasks ADD COLUMN project_task_id TEXT",
            "ALTER TABLE agent_tasks ADD COLUMN project_id TEXT",
            # Phase 2A — agent_tasks additive columns for canonical task model.
            # All nullable; existing rows continue to read unchanged.
            "ALTER TABLE agent_tasks ADD COLUMN parent_task_id TEXT",
            "ALTER TABLE agent_tasks ADD COLUMN root_task_id TEXT",
            "ALTER TABLE agent_tasks ADD COLUMN request_source TEXT",
            "ALTER TABLE agent_tasks ADD COLUMN requesting_user TEXT",
            "ALTER TABLE agent_tasks ADD COLUMN priority INTEGER",
            "ALTER TABLE agent_tasks ADD COLUMN updated_at REAL",
            "ALTER TABLE agent_tasks ADD COLUMN completed_at REAL",
            "ALTER TABLE agent_tasks ADD COLUMN summary TEXT",
            "ALTER TABLE agent_tasks ADD COLUMN errors_json TEXT",
            "ALTER TABLE agent_tasks ADD COLUMN requires_user_input INTEGER DEFAULT 0",
            "ALTER TABLE agent_tasks ADD COLUMN requires_approval INTEGER DEFAULT 0",
            "ALTER TABLE agent_tasks ADD COLUMN task_session_id TEXT",
            # Phase 2E — Chief-as-ingress designation. Nullable boolean
            # (SQLite uses 0/1); exactly one agent should carry the
            # flag at any time, enforced by ``set_chief_agent`` rather
            # than a CHECK constraint so back-fill stays simple.
            "ALTER TABLE managed_agents ADD COLUMN is_chief INTEGER DEFAULT 0",
            # Phase 2G — worker session isolation. Nullable: NULL/'' means
            # "general session" (today's behaviour). Populated for
            # delegated turns when ``worker_session_isolation.enabled``.
            "ALTER TABLE agent_messages ADD COLUMN session_id TEXT",
        ]
        for migration in _MIGRATIONS:
            try:
                self._conn.execute(migration)
            except sqlite3.OperationalError:
                pass  # Column already exists
        self._conn.commit()
        # One-time backfill so the new hard linkage requirement does not
        # break agents that already have unlinked tasks.
        self._backfill_unlinked_project_tasks()
        # Phase 2E — back-fill the Chief designation. Idempotent: only
        # runs when no agent is currently marked is_chief.
        self._backfill_chief_designation()

    def close(self) -> None:
        self._conn.close()

    # ── Phase 2C — Event emission helpers ─────────────────────────

    def _emit_task_event(self, event_type: Any, payload: Dict[str, Any]) -> None:
        """Publish a ``task.*`` event on the configured bus.

        No-op when no bus is wired (test/CLI callers). Event publishing
        is best-effort — a downstream subscriber raising must never break
        a task lifecycle operation.
        """
        if self._event_bus is None:
            return
        try:
            self._event_bus.publish(event_type, payload)
        except Exception:
            pass

    # ── Project-store linkage (Mission Control) ───────────────────

    def _project_store(self) -> Any:
        """Lazily resolve a ProjectStore for cross-store linkage.

        Injected one wins (tests); otherwise a default singleton is
        created on first use, mirroring projects_router's pattern.
        """
        if self._proj_store is None:
            from openjarvis.projects.store import ProjectStore

            self._proj_store = ProjectStore()
        return self._proj_store

    def validate_project_task(self, project_task_id: str) -> Dict[str, Any]:
        """Return the linked project task or raise ValueError.

        Enforces the hard requirement that every agent task references an
        existing project task or subtask.
        """
        ptid = str(project_task_id or "").strip()
        if not ptid:
            raise ValueError(
                "project_task_id is required: every agent task must be "
                "linked to a project task or subtask."
            )
        proj_task = self._project_store().get_task(ptid)
        if proj_task is None:
            raise ValueError(
                f"Linked project task not found: {ptid!r}"
            )
        return proj_task

    @staticmethod
    def _agent_status_to_project_status(status: str) -> str:
        normalized = str(status or "").strip().casefold()
        if normalized == "active":
            return "In Progress"
        if normalized == "completed":
            return "Done"
        if normalized == "failed":
            return "Blocked"
        return "Backlog"

    def _resolve_agent_work_project_task(
        self,
        *,
        agent_id: str,
        description: str,
        status: str,
        project_task_id: str,
    ) -> Dict[str, Any]:
        """Return the concrete project task an agent task should link to.

        The "Unassigned Work" migration creates one durable catch-all task per
        agent. New work routed through that catch-all still needs its own child
        task so Mission Control shows each chat request in the project tree.
        """
        proj_task = (
            self.validate_project_task(project_task_id)
            if str(project_task_id or "").strip()
            else self._ensure_unassigned_catchall_task(agent_id)
        )
        ps = self._project_store()
        project = ps.get_project(str(proj_task.get("project_id", "")))
        is_unassigned_catchall = (
            project is not None
            and project.get("name") == _UNASSIGNED_PROJECT_NAME
            and str(proj_task.get("title", "")).startswith("Unreconciled work")
            and not proj_task.get("parent_task_id")
        )
        if not is_unassigned_catchall:
            return proj_task

        agent = self.get_agent(agent_id)
        title = str(description or "Agent work").strip() or "Agent work"
        default_dates = _default_agent_project_task_dates()
        child = ps.create_task(
            proj_task["project_id"],
            parent_task_id=proj_task["id"],
            title=title[:160],
            description=description,
            type="Chore",
            status=self._agent_status_to_project_status(status),
            assigned_to=(agent or {}).get("name", "") or "",
            start_date=default_dates["start_date"],
            due_date=default_dates["due_date"],
        )
        return child

    def _ensure_unassigned_catchall_task(self, agent_id: str) -> Dict[str, Any]:
        ps = self._project_store()
        sys_proj = next(
            (
                p
                for p in ps.list_projects()
                if p.get("name") == _UNASSIGNED_PROJECT_NAME
            ),
            None,
        )
        if sys_proj is None:
            sys_proj = ps.create_project(
                name=_UNASSIGNED_PROJECT_NAME,
                description=(
                    "System catch-all for agent work that was not assigned "
                    "to a real project task yet. Reassign these tasks to a "
                    "real project task, then archive this project."
                ),
                status="Active",
                tags=["system", "needs-reconciliation"],
            )
        agent = self.get_agent(agent_id)
        aname = (agent or {}).get("name") or agent_id
        catchall_title = f"Unreconciled work — {aname}"
        existing = next(
            (
                t
                for t in ps.list_tasks(sys_proj["id"])
                if t.get("title") == catchall_title and not t.get("parent_task_id")
            ),
            None,
        )
        if existing is not None:
            return existing
        return ps.create_task(
            sys_proj["id"],
            title=catchall_title,
            description=(
                "Auto-created during the Mission Control migration. "
                "Reassign the agent's tasks to a real project task "
                "or subtask."
            ),
            type="Chore",
            status="Backlog",
            assigned_to=aname,
        )

    def _backfill_unlinked_project_tasks(self) -> None:
        """Link any pre-existing unlinked agent tasks to a catch-all task.

        Only touches the projects DB when there is actually unlinked work,
        so already-migrated / fresh installs pay no cost.
        """
        try:
            probe = self._conn.execute(
                "SELECT 1 FROM agent_tasks WHERE "
                "project_task_id IS NULL OR project_task_id = '' LIMIT 1"
            ).fetchone()
        except sqlite3.OperationalError:
            return  # agent_tasks table not present yet
        if probe is None:
            return

        ps = self._project_store()
        sys_proj = next(
            (
                p
                for p in ps.list_projects()
                if p.get("name") == _UNASSIGNED_PROJECT_NAME
            ),
            None,
        )
        if sys_proj is None:
            sys_proj = ps.create_project(
                name=_UNASSIGNED_PROJECT_NAME,
                description=(
                    "System catch-all for agent work created before "
                    "Mission Control linkage. Reassign these tasks to a "
                    "real project task, then archive this project."
                ),
                status="Active",
                tags=["system", "needs-reconciliation"],
            )

        rows = self._conn.execute(
            "SELECT id, agent_id FROM agent_tasks WHERE "
            "project_task_id IS NULL OR project_task_id = ''"
        ).fetchall()
        catchall: Dict[str, str] = {}
        for r in rows:
            agent_id = r["agent_id"]
            ptid = catchall.get(agent_id)
            if ptid is None:
                t = self._ensure_unassigned_catchall_task(agent_id)
                ptid = t["id"]
                catchall[agent_id] = ptid
            self._conn.execute(
                "UPDATE agent_tasks SET project_task_id = ?, project_id = ? "
                "WHERE id = ?",
                (ptid, sys_proj["id"], r["id"]),
            )
        self._conn.commit()

    # ── Agent CRUD ────────────────────────────────────────────────

    def create_agent(
        self,
        name: str,
        agent_type: str = "monitor_operative",
        config: Optional[Dict[str, Any]] = None,
        org_role: str = "",
        manager_agent_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        agent_id = uuid.uuid4().hex[:12]
        now = time.time()
        config_json = json.dumps(config or {})
        normalized_manager_id = self._normalize_manager_id(manager_agent_id)
        self._validate_manager_assignment(agent_id, normalized_manager_id)
        self._conn.execute(
            "INSERT INTO managed_agents"
            " (id, name, agent_type, org_role, manager_agent_id, config_json,"
            " status, summary_memory, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?, 'idle', '', ?, ?)",
            (
                agent_id,
                name,
                agent_type,
                (org_role or "").strip(),
                normalized_manager_id,
                config_json,
                now,
                now,
            ),
        )
        self._conn.commit()
        return self.get_agent(agent_id)  # type: ignore[return-value]

    def list_agents(self, include_archived: bool = False) -> List[Dict[str, Any]]:
        query = "SELECT * FROM managed_agents"
        if not include_archived:
            query += " WHERE status != 'archived'"
        query += " ORDER BY updated_at DESC"
        rows = self._conn.execute(query).fetchall()
        return [self._row_to_agent(r) for r in rows]

    def get_agent(self, agent_id: str) -> Optional[Dict[str, Any]]:
        row = self._conn.execute(
            "SELECT * FROM managed_agents WHERE id = ?", (agent_id,)
        ).fetchone()
        return self._row_to_agent(row) if row else None

    def update_agent(self, agent_id: str, **kwargs: Any) -> Dict[str, Any]:
        # Capture pre-update snapshot for the version log when config changes.
        prior_config: Optional[Dict[str, Any]] = None
        if "config" in kwargs:
            prior = self.get_agent(agent_id)
            prior_config = (prior or {}).get("config") or {}
        sets: List[str] = []
        vals: List[Any] = []
        for key in (
            "name",
            "agent_type",
            "status",
            "current_activity",
            "avatar_url",
            "avatar_mime_type",
            "avatar_file_name",
            "avatar_updated_at",
        ):
            if key in kwargs:
                sets.append(f"{key} = ?")
                vals.append(kwargs[key])
        if "org_role" in kwargs:
            sets.append("org_role = ?")
            vals.append((kwargs["org_role"] or "").strip())
        if "manager_agent_id" in kwargs:
            normalized_manager_id = self._normalize_manager_id(
                kwargs["manager_agent_id"]
            )
            self._validate_manager_assignment(agent_id, normalized_manager_id)
            sets.append("manager_agent_id = ?")
            vals.append(normalized_manager_id)
        if "config" in kwargs:
            sets.append("config_json = ?")
            vals.append(json.dumps(kwargs["config"]))
        total_runs_increment = kwargs.get("total_runs_increment", 0)
        if total_runs_increment:
            sets.append("total_runs = total_runs + ?")
            vals.append(total_runs_increment)
            sets.append("last_run_at = ?")
            vals.append(time.time())
        total_cost_increment = kwargs.get("total_cost_increment", 0)
        if total_cost_increment:
            sets.append("total_cost = total_cost + ?")
            vals.append(total_cost_increment)
        total_tokens_increment = kwargs.get("total_tokens_increment", 0)
        if total_tokens_increment:
            sets.append("total_tokens = total_tokens + ?")
            vals.append(total_tokens_increment)
        input_tokens_increment = kwargs.get("input_tokens_increment", 0)
        if input_tokens_increment:
            sets.append("input_tokens = input_tokens + ?")
            vals.append(input_tokens_increment)
        output_tokens_increment = kwargs.get("output_tokens_increment", 0)
        if output_tokens_increment:
            sets.append("output_tokens = output_tokens + ?")
            vals.append(output_tokens_increment)
        if "last_activity_at" in kwargs:
            sets.append("last_activity_at = ?")
            vals.append(kwargs["last_activity_at"])
        if "stall_retries" in kwargs:
            sets.append("stall_retries = ?")
            vals.append(kwargs["stall_retries"])
        sets.append("updated_at = ?")
        vals.append(time.time())
        vals.append(agent_id)
        self._conn.execute(
            f"UPDATE managed_agents SET {', '.join(sets)} WHERE id = ?", vals
        )
        self._conn.commit()
        # Phase 2A — append a config version row whenever the config blob
        # actually changed (no-op updates don't pollute history).
        if "config" in kwargs:
            new_config = kwargs["config"] or {}
            if (prior_config or {}) != (new_config or {}):
                try:
                    self._append_config_version(
                        agent_id=agent_id,
                        prior_config=prior_config or {},
                        new_config=new_config,
                        created_by=kwargs.get("updated_by"),
                        summary=kwargs.get("change_summary", ""),
                    )
                except Exception:
                    # Version capture is best-effort; never block an
                    # otherwise-successful update on a history write failure.
                    pass
        return self.get_agent(agent_id)  # type: ignore[return-value]

    # ── Config version history (Phase 2A, append-only) ───────────

    def _append_config_version(
        self,
        agent_id: str,
        prior_config: Dict[str, Any],
        new_config: Dict[str, Any],
        created_by: Optional[str] = None,
        summary: str = "",
    ) -> Dict[str, Any]:
        next_number = (
            self._conn.execute(
                "SELECT COALESCE(MAX(version_number), 0) + 1 AS n"
                " FROM agent_config_versions WHERE agent_id = ?",
                (agent_id,),
            ).fetchone()["n"]
        )
        diff = self._compute_config_diff(prior_config, new_config)
        version_id = uuid.uuid4().hex[:12]
        self._conn.execute(
            "INSERT INTO agent_config_versions"
            " (id, agent_id, version_number, snapshot_json, diff_json,"
            " summary, created_at, created_by)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                version_id,
                agent_id,
                int(next_number),
                json.dumps(new_config),
                json.dumps(diff),
                str(summary or "").strip(),
                time.time(),
                str(created_by or "").strip() or None,
            ),
        )
        self._conn.commit()
        return {
            "id": version_id,
            "agent_id": agent_id,
            "version_number": int(next_number),
            "snapshot": new_config,
            "diff": diff,
            "summary": str(summary or "").strip(),
            "created_by": str(created_by or "").strip() or None,
        }

    @staticmethod
    def _compute_config_diff(
        prior: Dict[str, Any], new: Dict[str, Any]
    ) -> Dict[str, Any]:
        added: Dict[str, Any] = {}
        removed: Dict[str, Any] = {}
        changed: Dict[str, Any] = {}
        for key in set(prior) | set(new):
            if key not in prior:
                added[key] = new[key]
            elif key not in new:
                removed[key] = prior[key]
            elif prior[key] != new[key]:
                changed[key] = {"from": prior[key], "to": new[key]}
        return {"added": added, "removed": removed, "changed": changed}

    def list_agent_config_versions(
        self, agent_id: str, limit: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        query = (
            "SELECT id, agent_id, version_number, snapshot_json, diff_json,"
            " summary, created_at, created_by"
            " FROM agent_config_versions WHERE agent_id = ?"
            " ORDER BY version_number DESC"
        )
        params: List[Any] = [agent_id]
        if limit is not None and limit > 0:
            query += " LIMIT ?"
            params.append(int(limit))
        rows = self._conn.execute(query, params).fetchall()
        return [
            {
                "id": r["id"],
                "agent_id": r["agent_id"],
                "version_number": r["version_number"],
                "snapshot": json.loads(r["snapshot_json"]),
                "diff": json.loads(r["diff_json"] or "{}"),
                "summary": r["summary"] or "",
                "created_at": r["created_at"],
                "created_by": r["created_by"],
            }
            for r in rows
        ]

    def revert_agent_config_to_version(
        self, agent_id: str, version_id: str, updated_by: Optional[str] = None
    ) -> Dict[str, Any]:
        """Append a new version that restores an earlier snapshot.

        Non-destructive: the prior version row is preserved and the revert
        itself becomes a new row in history.
        """
        row = self._conn.execute(
            "SELECT snapshot_json, version_number FROM agent_config_versions"
            " WHERE id = ? AND agent_id = ?",
            (version_id, agent_id),
        ).fetchone()
        if row is None:
            raise ValueError(
                f"Version {version_id!r} not found for agent {agent_id!r}"
            )
        snapshot = json.loads(row["snapshot_json"])
        summary = f"Revert to version {int(row['version_number'])}"
        return self.update_agent(
            agent_id,
            config=snapshot,
            updated_by=updated_by,
            change_summary=summary,
        )

    # ── Phase 2E — Chief designation (single-row flag) ────────────

    # Role substrings that already mark an agent as "chief" today in
    # ``managed_agent_runtime._role_guidance``. Used for the one-time
    # back-fill so existing installs auto-promote a sensible Chief.
    _CHIEF_ROLE_HINTS = (
        "chief orchestrator",
        "chief executive officer",
        "ceo",
    )

    def _backfill_chief_designation(self) -> None:
        """Mark the first matching agent as Chief if none currently is.

        Idempotent: if any row already has ``is_chief = 1``, this is a
        no-op. Runs once at startup; subsequent ``set_chief_agent`` calls
        replace the designation atomically.
        """
        try:
            existing = self._conn.execute(
                "SELECT id FROM managed_agents WHERE is_chief = 1 LIMIT 1"
            ).fetchone()
            if existing is not None:
                return
            rows = self._conn.execute(
                "SELECT id, org_role FROM managed_agents WHERE status != 'archived'"
            ).fetchall()
            for row in rows:
                role = str(row["org_role"] or "").strip().casefold()
                if any(hint in role for hint in self._CHIEF_ROLE_HINTS):
                    self._conn.execute(
                        "UPDATE managed_agents SET is_chief = 1 WHERE id = ?",
                        (row["id"],),
                    )
                    self._conn.commit()
                    return
        except Exception:
            # Back-fill is best-effort. The endpoint already returns
            # 412 with a CTA when no Chief is set, so a failed back-fill
            # degrades to "user designates manually".
            pass

    def get_chief_agent(self) -> Optional[Dict[str, Any]]:
        """Return the currently-designated Chief agent record, or None."""
        row = self._conn.execute(
            "SELECT * FROM managed_agents"
            " WHERE is_chief = 1 AND status != 'archived' LIMIT 1"
        ).fetchone()
        return self._row_to_agent(row) if row else None

    def set_chief_agent(self, agent_id: str) -> Dict[str, Any]:
        """Atomically clear the Chief flag from any prior row and set it
        on ``agent_id``.

        Raises ``ValueError`` if the named agent does not exist or is
        archived. Idempotent: setting the existing Chief is a no-op
        beyond bumping ``updated_at``.
        """
        target = self.get_agent(agent_id)
        if target is None:
            raise ValueError(f"Agent not found: {agent_id!r}")
        if target.get("status") == "archived":
            raise ValueError(
                f"Cannot designate archived agent as Chief: {agent_id!r}"
            )
        now = time.time()
        # Single transaction: clear all, set one. SQLite's default
        # isolation gives us atomicity for this pair of statements
        # because we commit only once.
        try:
            self._conn.execute(
                "UPDATE managed_agents SET is_chief = 0 WHERE is_chief = 1"
            )
            self._conn.execute(
                "UPDATE managed_agents SET is_chief = 1, updated_at = ?"
                " WHERE id = ?",
                (now, agent_id),
            )
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise
        return self.get_agent(agent_id)  # type: ignore[return-value]

    def clear_chief_designation(self) -> None:
        """Remove the Chief flag from all agents.

        Useful for tests and for an admin "no Chief configured" state
        (the new ingress endpoint then returns 412 with a CTA).
        """
        self._conn.execute(
            "UPDATE managed_agents SET is_chief = 0 WHERE is_chief = 1"
        )
        self._conn.commit()

    def delete_agent(self, agent_id: str) -> None:
        self._set_status(agent_id, "archived")

    def pause_agent(self, agent_id: str) -> None:
        self._set_status(agent_id, "paused")

    def resume_agent(self, agent_id: str) -> None:
        self._set_status(agent_id, "idle")

    def _set_status(self, agent_id: str, status: str) -> None:
        self._conn.execute(
            "UPDATE managed_agents SET status = ?, updated_at = ? WHERE id = ?",
            (status, time.time(), agent_id),
        )
        self._conn.commit()

    # ── Tick concurrency guard ────────────────────────────────────

    def start_tick(self, agent_id: str) -> None:
        """Mark agent as running. Raises ValueError if already running."""
        agent = self.get_agent(agent_id)
        if agent and agent["status"] == "running":
            raise ValueError(f"Agent {agent_id} is already executing a tick")
        self._set_status(agent_id, "running")

    def end_tick(self, agent_id: str) -> None:
        self._conn.execute(
            "UPDATE managed_agents SET status = 'idle', "
            "current_activity = '', updated_at = ? WHERE id = ?",
            (time.time(), agent_id),
        )
        self._conn.commit()

    def reap_stale_running(self, stale_seconds: int = 120) -> int:
        """Reset agents stuck 'running' with no recent heartbeat to idle.

        An interrupted run (server restart / crash / killed thread) never
        reaches :meth:`end_tick`, so the agent stays ``status='running'``
        with a frozen ``current_activity`` forever and can't be re-run.
        Call this on server startup. Returns the number reaped.
        """
        now = time.time()
        cur = self._conn.execute(
            "UPDATE managed_agents SET status = 'idle', "
            "current_activity = '', updated_at = ? "
            "WHERE status = 'running' AND "
            "(last_activity_at IS NULL OR last_activity_at < ?)",
            (now, now - stale_seconds),
        )
        self._conn.commit()
        return cur.rowcount or 0

    # ── Checkpoints ───────────────────────────────────────────────

    _CHECKPOINT_RETENTION = 5

    def save_checkpoint(
        self,
        agent_id: str,
        tick_id: str,
        conversation_state: dict,
        tool_state: dict,
    ) -> dict:
        cp_id = uuid4().hex[:16]
        now = time.time()
        self._conn.execute(
            "INSERT INTO agent_checkpoints"
            " (id, agent_id, tick_id, conversation_state, tool_state, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (
                cp_id,
                agent_id,
                tick_id,
                json.dumps(conversation_state),
                json.dumps(tool_state),
                now,
            ),
        )
        # Prune old checkpoints beyond retention limit
        self._conn.execute(
            "DELETE FROM agent_checkpoints WHERE agent_id = ? AND id NOT IN "
            "(SELECT id FROM agent_checkpoints WHERE agent_id = ?"
            " ORDER BY created_at DESC LIMIT ?)",
            (agent_id, agent_id, self._CHECKPOINT_RETENTION),
        )
        self._conn.commit()
        return {
            "id": cp_id,
            "agent_id": agent_id,
            "tick_id": tick_id,
            "created_at": now,
        }

    def list_checkpoints(self, agent_id: str) -> list:
        rows = self._conn.execute(
            "SELECT * FROM agent_checkpoints"
            " WHERE agent_id = ? ORDER BY created_at DESC",
            (agent_id,),
        ).fetchall()
        return [self._row_to_checkpoint(r) for r in rows]

    def get_latest_checkpoint(self, agent_id: str) -> Optional[Dict[str, Any]]:
        row = self._conn.execute(
            "SELECT * FROM agent_checkpoints"
            " WHERE agent_id = ? ORDER BY created_at DESC LIMIT 1",
            (agent_id,),
        ).fetchone()
        return self._row_to_checkpoint(row) if row else None

    def recover_agent(self, agent_id: str) -> Optional[Dict[str, Any]]:
        checkpoint = self.get_latest_checkpoint(agent_id)
        # Always reset to idle — clearing the error state is the primary purpose
        self.update_agent(agent_id, status="idle")
        return checkpoint

    @staticmethod
    def _row_to_checkpoint(row: sqlite3.Row) -> Dict[str, Any]:
        return {
            "id": row["id"],
            "agent_id": row["agent_id"],
            "tick_id": row["tick_id"],
            "conversation_state": json.loads(row["conversation_state"]),
            "tool_state": json.loads(row["tool_state"]),
            "created_at": row["created_at"],
        }

    # ── Summary memory ────────────────────────────────────────────

    def update_summary_memory(self, agent_id: str, summary: str) -> None:
        truncated = summary[:_SUMMARY_MAX]
        self._conn.execute(
            "UPDATE managed_agents SET summary_memory = ?, updated_at = ? WHERE id = ?",
            (truncated, time.time(), agent_id),
        )
        self._conn.commit()

    # ── Task CRUD ─────────────────────────────────────────────────

    def create_task(
        self,
        agent_id: str,
        description: str,
        status: str = "pending",
        assigned_by_agent_id: Optional[str] = None,
        project_task_id: Optional[str] = None,
        project_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        # Hard requirement: agent work must be tied to a project task or
        # subtask for tracking and documentation. Raises ValueError if the
        # link is missing or does not resolve to an existing project task.
        proj_task = self._resolve_agent_work_project_task(
            agent_id=agent_id,
            description=description,
            status=status,
            project_task_id=project_task_id or "",
        )
        resolved_project_id = (
            str(project_id).strip()
            if project_id
            else proj_task.get("project_id")
        )
        task_id = uuid.uuid4().hex[:12]
        now = time.time()
        normalized_assigned_by = self._normalize_manager_id(assigned_by_agent_id)
        self._conn.execute(
            "INSERT INTO agent_tasks "
            "(id, agent_id, assigned_by_agent_id, description, status, "
            "project_task_id, project_id, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                task_id,
                agent_id,
                normalized_assigned_by,
                description,
                status,
                str(proj_task["id"]).strip(),
                resolved_project_id,
                now,
            ),
        )
        self._conn.commit()
        # Phase 2C — task.created event (no-op when no bus wired).
        from openjarvis.core.events import EventType

        self._emit_task_event(
            EventType.TASK_CREATED,
            {
                "task_id": task_id,
                "agent_id": agent_id,
                "assigned_by_agent_id": normalized_assigned_by,
                "description": description,
                "status": status,
                "project_task_id": str(proj_task["id"]).strip(),
                "project_id": resolved_project_id,
                "created_at": now,
            },
        )
        # If the new task was created by another agent, this is a
        # delegation — also emit task.delegated so the activity sidebar
        # has a first-class signal (the existing delegation tools no
        # longer need to emit this separately).
        if normalized_assigned_by:
            self._emit_task_event(
                EventType.TASK_DELEGATED,
                {
                    "task_id": task_id,
                    "from_agent_id": normalized_assigned_by,
                    "to_agent_id": agent_id,
                    "description": description,
                    "project_task_id": str(proj_task["id"]).strip(),
                },
            )
        return self._get_task(task_id)  # type: ignore[return-value]

    def list_tasks(
        self, agent_id: str, status: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        query = "SELECT * FROM agent_tasks WHERE agent_id = ?"
        params: List[Any] = [agent_id]
        if status:
            query += " AND status = ?"
            params.append(status)
        query += " ORDER BY created_at DESC"
        rows = self._conn.execute(query, params).fetchall()
        return [self._row_to_task(r) for r in rows]

    @staticmethod
    def _parse_task_start(value: Any) -> Optional[float]:
        raw = str(value or "").strip()
        if not raw:
            return None
        try:
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return None
        if dt.tzinfo is None:
            return dt.timestamp()
        return dt.astimezone(timezone.utc).timestamp()

    def _is_runnable_agent_task(
        self,
        task: Dict[str, Any],
        *,
        now: Optional[float] = None,
    ) -> bool:
        if str(task.get("status") or "") in ("completed", "failed"):
            return False
        project_task_id = str(task.get("project_task_id") or "").strip()
        if not project_task_id:
            return False
        try:
            project_task = self._project_store().get_task(project_task_id)
        except Exception:
            return False
        if project_task is None:
            return False
        if project_task.get("status") in ("Done", "Cancelled"):
            return False
        start_ts = self._parse_task_start(project_task.get("start_date"))
        return start_ts is None or start_ts <= (now or time.time())

    def list_runnable_tasks(self, agent_id: str) -> List[Dict[str, Any]]:
        now = time.time()
        return [
            task
            for task in self.list_tasks(agent_id)
            if self._is_runnable_agent_task(task, now=now)
        ]

    def has_runnable_task(self, agent_id: str) -> bool:
        return bool(self.list_runnable_tasks(agent_id))

    def has_open_linked_task(self, agent_id: str) -> bool:
        return any(
            task.get("project_task_id")
            and str(task.get("status") or "") not in ("completed", "failed")
            for task in self.list_tasks(agent_id)
        )

    def reactivate_project_task_work(
        self,
        project_task_id: str,
    ) -> List[Dict[str, Any]]:
        """Ensure due project work has an open linked agent task.

        Used when a human moves a project task's start date to today. The
        scheduler only sees ``agent_tasks``; this bridges manual project edits
        back into runnable agent work.
        """
        ptid = str(project_task_id or "").strip()
        if not ptid:
            return []
        project_task = self._project_store().get_task(ptid)
        if project_task is None:
            return []
        if str(project_task.get("status") or "") in ("Done", "Cancelled"):
            return []
        start_ts = self._parse_task_start(project_task.get("start_date"))
        if start_ts is not None and start_ts > time.time():
            return []

        rows = self._conn.execute(
            "SELECT * FROM agent_tasks WHERE project_task_id = ?",
            (ptid,),
        ).fetchall()
        reactivated: List[Dict[str, Any]] = []
        for row in rows:
            task = self._row_to_task(row)
            if str(task.get("status") or "") in ("completed", "failed"):
                progress = dict(task.get("progress") or {})
                progress["reactivated"] = (
                    "Project task start date is due; reopened for agent processing."
                )
                reactivated.append(
                    self.update_task(
                        task["id"],
                        status="active",
                        progress=progress,
                    )
                )
            else:
                reactivated.append(task)

        if reactivated:
            return reactivated

        assignee = str(
            project_task.get("assigned_to") or project_task.get("owner") or ""
        ).strip()
        if not assignee:
            return []
        match = next(
            (
                agent
                for agent in self.list_agents()
                if str(agent.get("name", "")).strip().casefold()
                == assignee.casefold()
            ),
            None,
        )
        if match is None:
            return []
        created = self.create_task(
            match["id"],
            description=str(project_task.get("title") or "Project task"),
            status="active",
            project_task_id=ptid,
            project_id=str(project_task.get("project_id") or "") or None,
        )
        return [created]

    def list_tasks_assigned_by(
        self, assigned_by_agent_id: str, status: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        query = "SELECT * FROM agent_tasks WHERE assigned_by_agent_id = ?"
        params: List[Any] = [assigned_by_agent_id]
        if status:
            query += " AND status = ?"
            params.append(status)
        query += " ORDER BY created_at DESC"
        rows = self._conn.execute(query, params).fetchall()
        return [self._row_to_task(r) for r in rows]

    def update_task(self, task_id: str, **kwargs: Any) -> Dict[str, Any]:
        prior = self._get_task(task_id)
        prior_status = str((prior or {}).get("status") or "")
        sets: List[str] = []
        vals: List[Any] = []
        for key in ("description", "status"):
            if key in kwargs:
                sets.append(f"{key} = ?")
                vals.append(kwargs[key])
        for key in ("requires_approval", "requires_user_input"):
            if key in kwargs:
                sets.append(f"{key} = ?")
                vals.append(1 if kwargs[key] else 0)
        if "progress" in kwargs:
            sets.append("progress_json = ?")
            vals.append(json.dumps(kwargs["progress"]))
        if "findings" in kwargs:
            sets.append("findings_json = ?")
            vals.append(json.dumps(kwargs["findings"]))
        if not sets:
            return self._get_task(task_id)  # type: ignore[return-value]
        vals.append(task_id)
        self._conn.execute(
            f"UPDATE agent_tasks SET {', '.join(sets)} WHERE id = ?", vals
        )
        self._conn.commit()
        updated = self._get_task(task_id)
        # Phase 2C — task.* events. Always emit task.updated; emit
        # task.completed / task.failed when status crosses into a
        # terminal state.
        from openjarvis.core.events import EventType

        new_status = str((updated or {}).get("status") or "")
        self._emit_task_event(
            EventType.TASK_UPDATED,
            {
                "task_id": task_id,
                "agent_id": (updated or {}).get("agent_id"),
                "prior_status": prior_status,
                "status": new_status,
                "changed_keys": list(kwargs.keys()),
            },
        )
        if new_status != prior_status:
            if new_status == "completed":
                self._emit_task_event(
                    EventType.TASK_COMPLETED,
                    {
                        "task_id": task_id,
                        "agent_id": (updated or {}).get("agent_id"),
                        "prior_status": prior_status,
                    },
                )
            elif new_status == "failed":
                self._emit_task_event(
                    EventType.TASK_FAILED,
                    {
                        "task_id": task_id,
                        "agent_id": (updated or {}).get("agent_id"),
                        "prior_status": prior_status,
                    },
                )
        return updated  # type: ignore[return-value]

    def delete_task(self, task_id: str) -> None:
        self._conn.execute("DELETE FROM agent_tasks WHERE id = ?", (task_id,))
        self._conn.commit()

    def _get_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        row = self._conn.execute(
            "SELECT * FROM agent_tasks WHERE id = ?", (task_id,)
        ).fetchone()
        return self._row_to_task(row) if row else None

    # ── Channel bindings ──────────────────────────────────────────

    def bind_channel(
        self,
        agent_id: str,
        channel_type: str,
        config: Optional[Dict[str, Any]] = None,
        routing_mode: str = "dedicated",
    ) -> Dict[str, Any]:
        binding_id = uuid.uuid4().hex[:12]
        session_id = uuid.uuid4().hex[:16]
        config_json = json.dumps(config or {})
        self._conn.execute(
            "INSERT INTO channel_bindings "
            "(id, agent_id, channel_type, config_json, session_id, routing_mode) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (binding_id, agent_id, channel_type, config_json, session_id, routing_mode),
        )
        self._conn.commit()
        return self._get_binding(binding_id)  # type: ignore[return-value]

    def list_channel_bindings(self, agent_id: str) -> List[Dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM channel_bindings WHERE agent_id = ?", (agent_id,)
        ).fetchall()
        return [self._row_to_binding(r) for r in rows]

    def unbind_channel(self, binding_id: str) -> None:
        self._conn.execute("DELETE FROM channel_bindings WHERE id = ?", (binding_id,))
        self._conn.commit()

    def _get_binding(self, binding_id: str) -> Optional[Dict[str, Any]]:
        row = self._conn.execute(
            "SELECT * FROM channel_bindings WHERE id = ?", (binding_id,)
        ).fetchone()
        return self._row_to_binding(row) if row else None

    def find_binding_for_channel(
        self, channel_type: str, channel_id: str
    ) -> Optional[Dict[str, Any]]:
        """Find the first binding for a specific channel."""
        bindings = self.find_bindings_for_channel(channel_type, channel_id)
        return bindings[0] if bindings else None

    def find_bindings_for_channel(
        self, channel_type: str, channel_id: str
    ) -> List[Dict[str, Any]]:
        """Find all bindings that target a specific channel/chat ID.

        Telegram historically used both ``config.channel`` and
        ``config.chat_id`` in different call sites, so we match both.
        """
        rows = self._conn.execute(
            "SELECT * FROM channel_bindings WHERE channel_type = ?",
            (channel_type,),
        ).fetchall()
        matches: List[Dict[str, Any]] = []
        for row in rows:
            binding = self._row_to_binding(row)
            config = binding.get("config", {})
            if (
                str(config.get("channel", "")).strip() == channel_id
                or str(config.get("chat_id", "")).strip() == channel_id
            ):
                matches.append(binding)
        return matches

    # ── Templates ─────────────────────────────────────────────────

    @staticmethod
    def list_templates() -> List[Dict[str, Any]]:
        """Discover built-in and user templates."""
        try:
            from openjarvis.agents.library import list_templates

            return list_templates()
        except Exception:
            return []

    def create_from_template(
        self,
        template_id: str,
        name: str,
        overrides: Optional[Dict[str, Any]] = None,
        *,
        org_role: str = "",
        manager_agent_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Create an agent from a template with optional overrides."""
        templates = self.list_templates()
        tpl = next((t for t in templates if t.get("id") == template_id), None)
        if not tpl:
            raise ValueError(f"Template not found: {template_id}")
        skip = {"id", "name", "description", "source"}
        config = {k: v for k, v in tpl.items() if k not in skip}
        if overrides:
            config.update(overrides)
        config.setdefault("template_id", template_id)
        agent_type = config.pop("agent_type", "monitor_operative")

        # Expand system_prompt_template with instruction
        prompt_tpl = config.pop("system_prompt_template", "")
        if prompt_tpl:
            instruction = config.get("instruction", "")
            config["system_prompt"] = prompt_tpl.format(
                instruction=instruction or "(No specific instruction provided)",
            )

        return self.create_agent(
            name=name,
            agent_type=agent_type,
            config=config,
            org_role=org_role,
            manager_agent_id=manager_agent_id,
        )

    @staticmethod
    def _normalize_manager_id(manager_agent_id: Optional[str]) -> Optional[str]:
        value = str(manager_agent_id or "").strip()
        return value or None

    def _validate_manager_assignment(
        self,
        agent_id: str,
        manager_agent_id: Optional[str],
    ) -> None:
        if not manager_agent_id:
            return
        if manager_agent_id == agent_id:
            raise ValueError("An agent cannot report to itself.")
        manager = self.get_agent(manager_agent_id)
        if manager is None:
            raise ValueError(f"Manager agent not found: {manager_agent_id}")
        seen: set[str] = {agent_id}
        current_manager_id = manager_agent_id
        while current_manager_id:
            if current_manager_id in seen:
                raise ValueError("This reporting change would create a cycle.")
            seen.add(current_manager_id)
            current = self.get_agent(current_manager_id)
            if current is None:
                break
            current_manager_id = self._normalize_manager_id(
                current.get("manager_agent_id")
            )

    # ── Message queue ─────────────────────────────────────────────

    def send_message(
        self,
        agent_id: str,
        content: str,
        mode: str = "queued",
        *,
        session_id: Optional[str] = None,
    ) -> dict:
        msg_id = uuid4().hex[:16]
        now = time.time()
        scope = str(session_id or "").strip() or None
        self._conn.execute(
            "INSERT INTO agent_messages"
            " (id, agent_id, direction, content, mode, status, created_at,"
            " session_id)"
            " VALUES (?, ?, 'user_to_agent', ?, ?, 'pending', ?, ?)",
            (msg_id, agent_id, content, mode, now, scope),
        )
        self._conn.commit()
        return {
            "id": msg_id,
            "agent_id": agent_id,
            "direction": "user_to_agent",
            "content": content,
            "mode": mode,
            "status": "pending",
            "created_at": now,
            "session_id": scope,
        }

    def store_agent_response(
        self,
        agent_id: str,
        content: str,
        tool_calls: Optional[list] = None,
        *,
        session_id: Optional[str] = None,
    ) -> dict:
        """Store an agent-to-user response message.

        ``tool_calls`` is an optional list of ``{tool, arguments, result,
        success, latency}`` dicts captured during the turn. They are stored
        as JSON alongside the message so the UI can replay them after a
        page reload.

        ``session_id`` (Phase 2G) tags the row with a per-task scope so
        delegated turns can read a clean slice. ``None`` / empty means
        the general per-agent session (today's behaviour).
        """
        msg_id = uuid4().hex[:16]
        now = time.time()
        tool_calls_json = json.dumps(tool_calls) if tool_calls else None
        scope = str(session_id or "").strip() or None
        self._conn.execute(
            "INSERT INTO agent_messages"
            " (id, agent_id, direction, content, mode, status, created_at,"
            " tool_calls, session_id)"
            " VALUES (?, ?, 'agent_to_user', ?, 'immediate', 'delivered', ?, ?, ?)",
            (msg_id, agent_id, content, now, tool_calls_json, scope),
        )
        self._conn.commit()
        return {
            "id": msg_id,
            "agent_id": agent_id,
            "direction": "agent_to_user",
            "content": content,
            "mode": "immediate",
            "session_id": scope,
            "status": "delivered",
            "created_at": now,
            "tool_calls": tool_calls or None,
        }

    def list_messages(
        self,
        agent_id: str,
        limit: int = 50,
        *,
        session_id: Optional[str] = None,
        include_all_sessions: bool = False,
    ) -> list[dict]:
        """List messages for ``agent_id`` (newest first).

        Phase 2G scope rules:

        * ``session_id`` non-empty — return rows tagged with exactly that
          scope (regardless of the isolation flag).
        * ``include_all_sessions`` True — return every row for the agent
          (the audit view's full read, regardless of the flag).
        * Otherwise: when ``worker_session_isolation.enabled`` is True,
          return only **untagged** rows (general session); when False,
          return every row (byte-identical to pre-Phase-2G behaviour).
        """
        scope = str(session_id or "").strip()
        if scope:
            rows = self._conn.execute(
                "SELECT * FROM agent_messages"
                " WHERE agent_id = ? AND session_id = ?"
                " ORDER BY created_at DESC LIMIT ?",
                (agent_id, scope, limit),
            ).fetchall()
        elif include_all_sessions or not _worker_session_isolation_enabled():
            rows = self._conn.execute(
                "SELECT * FROM agent_messages"
                " WHERE agent_id = ? ORDER BY created_at DESC LIMIT ?",
                (agent_id, limit),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM agent_messages"
                " WHERE agent_id = ?"
                " AND (session_id IS NULL OR session_id = '')"
                " ORDER BY created_at DESC LIMIT ?",
                (agent_id, limit),
            ).fetchall()
        return [self._row_to_message(r) for r in rows]

    def get_pending_messages(self, agent_id: str) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM agent_messages"
            " WHERE agent_id = ? AND direction = 'user_to_agent'"
            " AND status = 'pending' ORDER BY created_at ASC",
            (agent_id,),
        ).fetchall()
        return [self._row_to_message(r) for r in rows]

    def mark_message_delivered(self, message_id: str) -> None:
        self._conn.execute(
            "UPDATE agent_messages SET status = 'delivered' WHERE id = ?",
            (message_id,),
        )
        self._conn.commit()

    def add_agent_response(self, agent_id: str, content: str) -> dict:
        msg_id = uuid4().hex[:16]
        now = time.time()
        _sql = (
            "INSERT INTO agent_messages"
            " (id, agent_id, direction, content, mode, status, created_at)"
            " VALUES (?, ?, 'agent_to_user', ?, 'immediate', 'responded', ?)"
        )
        self._conn.execute(_sql, (msg_id, agent_id, content, now))
        self._conn.commit()
        return {
            "id": msg_id,
            "agent_id": agent_id,
            "direction": "agent_to_user",
            "content": content,
            "mode": "immediate",
            "status": "responded",
            "created_at": now,
        }

    @staticmethod
    def _row_to_message(row: sqlite3.Row) -> dict:
        tool_calls = None
        try:
            session_id = row["session_id"]
        except (IndexError, KeyError):
            session_id = None
        try:
            raw = row["tool_calls"]
        except (IndexError, KeyError):
            raw = None
        if raw:
            try:
                tool_calls = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                tool_calls = None
        return {
            "id": row["id"],
            "agent_id": row["agent_id"],
            "direction": row["direction"],
            "content": row["content"],
            "mode": row["mode"],
            "status": row["status"],
            "created_at": row["created_at"],
            "tool_calls": tool_calls,
            "session_id": session_id,
        }

    # ── Learning log ──────────────────────────────────────────

    def add_learning_log(
        self,
        agent_id: str,
        event_type: str,
        description: str = "",
        data: dict | None = None,
    ) -> dict:
        log_id = uuid4().hex[:16]
        now = time.time()
        self._conn.execute(
            "INSERT INTO agent_learning_log"
            " (id, agent_id, event_type, description, data, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (log_id, agent_id, event_type, description, json.dumps(data or {}), now),
        )
        self._conn.commit()
        return {
            "id": log_id,
            "agent_id": agent_id,
            "event_type": event_type,
            "description": description,
            "data": data or {},
            "created_at": now,
        }

    def list_learning_log(self, agent_id: str, limit: int = 50) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM agent_learning_log"
            " WHERE agent_id = ? ORDER BY created_at DESC LIMIT ?",
            (agent_id, limit),
        ).fetchall()
        return [
            {
                "id": r["id"],
                "agent_id": r["agent_id"],
                "event_type": r["event_type"],
                "description": r["description"],
                "data": json.loads(r["data"] or "{}"),
                "created_at": r["created_at"],
            }
            for r in rows
        ]

    # ── Row converters ────────────────────────────────────────────

    @staticmethod
    def _row_to_agent(row: sqlite3.Row) -> Dict[str, Any]:
        config_raw = row["config_json"]
        keys = row.keys()
        return {
            "id": row["id"],
            "name": row["name"],
            "agent_type": row["agent_type"],
            "org_role": row["org_role"] or "",
            "manager_agent_id": row["manager_agent_id"],
            "config": json.loads(config_raw) if config_raw else {},
            "status": row["status"],
            "summary_memory": row["summary_memory"] or "",
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "total_tokens": row["total_tokens"] or 0,
            "total_cost": row["total_cost"] or 0.0,
            "total_runs": row["total_runs"] or 0,
            "last_run_at": row["last_run_at"],
            "last_activity_at": row["last_activity_at"],
            "stall_retries": row["stall_retries"] or 0,
            "current_activity": row["current_activity"] or "",
            "input_tokens": row["input_tokens"] or 0,
            "output_tokens": row["output_tokens"] or 0,
            "avatar_url": row["avatar_url"] if "avatar_url" in keys else None,
            "avatar_mime_type": (
                row["avatar_mime_type"] if "avatar_mime_type" in keys else None
            ),
            "avatar_file_name": (
                row["avatar_file_name"] if "avatar_file_name" in keys else None
            ),
            "avatar_updated_at": (
                row["avatar_updated_at"] if "avatar_updated_at" in keys else None
            ),
            # Phase 2E — Chief designation. Defaults False so legacy
            # rows from before the migration read as non-chief.
            "is_chief": bool(row["is_chief"]) if "is_chief" in keys else False,
        }

    @staticmethod
    def _row_to_task(row: sqlite3.Row) -> Dict[str, Any]:
        progress_raw = row["progress_json"]
        findings_raw = row["findings_json"]
        keys = row.keys()

        def _opt(name: str) -> Any:
            return row[name] if name in keys else None

        errors_raw = _opt("errors_json")
        return {
            "id": row["id"],
            "agent_id": row["agent_id"],
            "assigned_by_agent_id": row["assigned_by_agent_id"],
            "description": row["description"],
            "status": row["status"],
            "progress": json.loads(progress_raw) if progress_raw else {},
            "findings": json.loads(findings_raw) if findings_raw else [],
            "project_task_id": _opt("project_task_id"),
            "project_id": _opt("project_id"),
            "created_at": row["created_at"],
            # Phase 2A — canonical task model fields. All nullable; back-fill
            # is intentionally lazy (callers see None when the column was
            # never written, never crash).
            "parent_task_id": _opt("parent_task_id"),
            "root_task_id": _opt("root_task_id"),
            "request_source": _opt("request_source"),
            "requesting_user": _opt("requesting_user"),
            "priority": _opt("priority"),
            "updated_at": _opt("updated_at"),
            "completed_at": _opt("completed_at"),
            "summary": _opt("summary"),
            "errors": json.loads(errors_raw) if errors_raw else [],
            "requires_user_input": bool(_opt("requires_user_input") or 0),
            "requires_approval": bool(_opt("requires_approval") or 0),
            "task_session_id": _opt("task_session_id"),
        }

    @staticmethod
    def _row_to_binding(row: sqlite3.Row) -> Dict[str, Any]:
        config_raw = row["config_json"]
        return {
            "id": row["id"],
            "agent_id": row["agent_id"],
            "channel_type": row["channel_type"],
            "config": json.loads(config_raw) if config_raw else {},
            "session_id": row["session_id"] or "",
            "routing_mode": row["routing_mode"] or "auto",
        }
