"""Phase 2G stage 1 — schema + config + session-aware AgentManager helpers.

Covers the migration, the new ``session_id`` parameters on
``send_message`` / ``store_agent_response`` / ``list_messages``, the
flag-gated reader semantics (untagged-only when on; byte-identical when
off), the ``include_all_sessions`` audit hatch, and the new event types.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from openjarvis.agents.manager import AgentManager
from openjarvis.core.config import WorkerSessionIsolationConfig
from openjarvis.core.events import EventType

_FLAG_HELPER = "openjarvis.agents.manager._worker_session_isolation_enabled"


def _new_agent(manager: AgentManager, *, name: str = "Worker") -> dict:
    return manager.create_agent(
        name=name,
        agent_type="simple",
        config={"system_prompt": "You do work."},
    )


# --- config + events -------------------------------------------------


def test_worker_session_isolation_config_defaults_off():
    cfg = WorkerSessionIsolationConfig()
    assert cfg.enabled is False


def test_session_fork_and_merge_event_types_exist():
    assert EventType.AGENT_SESSION_FORKED.value == "agent.session.forked"
    assert EventType.AGENT_SESSION_MERGED.value == "agent.session.merged"


# --- schema ---------------------------------------------------------


def test_agent_messages_session_id_column_present():
    with tempfile.TemporaryDirectory() as tmpdir:
        manager = AgentManager(db_path=str(Path(tmpdir) / "agents.db"))
        try:
            cols = [
                r[1]
                for r in manager._conn.execute(
                    "PRAGMA table_info(agent_messages)"
                ).fetchall()
            ]
            assert "session_id" in cols
        finally:
            manager.close()


# --- write-side: session_id persists --------------------------------


def test_send_message_persists_session_id():
    with tempfile.TemporaryDirectory() as tmpdir:
        manager = AgentManager(db_path=str(Path(tmpdir) / "agents.db"))
        try:
            agent = _new_agent(manager)
            msg = manager.send_message(
                agent["id"], "scoped", mode="delegated", session_id="sess-A"
            )
            assert msg["session_id"] == "sess-A"
            row = manager._conn.execute(
                "SELECT session_id FROM agent_messages WHERE id = ?",
                (msg["id"],),
            ).fetchone()
            assert row[0] == "sess-A"
        finally:
            manager.close()


def test_send_message_default_session_is_null():
    with tempfile.TemporaryDirectory() as tmpdir:
        manager = AgentManager(db_path=str(Path(tmpdir) / "agents.db"))
        try:
            agent = _new_agent(manager)
            msg = manager.send_message(agent["id"], "general")
            row = manager._conn.execute(
                "SELECT session_id FROM agent_messages WHERE id = ?",
                (msg["id"],),
            ).fetchone()
            assert row[0] is None
            assert msg["session_id"] is None
        finally:
            manager.close()


def test_store_agent_response_persists_session_id():
    with tempfile.TemporaryDirectory() as tmpdir:
        manager = AgentManager(db_path=str(Path(tmpdir) / "agents.db"))
        try:
            agent = _new_agent(manager)
            stored = manager.store_agent_response(
                agent["id"], "reply", session_id="sess-B"
            )
            assert stored["session_id"] == "sess-B"
            row = manager._conn.execute(
                "SELECT session_id FROM agent_messages WHERE id = ?",
                (stored["id"],),
            ).fetchone()
            assert row[0] == "sess-B"
        finally:
            manager.close()


# --- read-side: list_messages semantics -----------------------------


def _seed_three(manager: AgentManager, agent_id: str) -> None:
    """One untagged message, then one each in two distinct sessions."""
    manager.send_message(agent_id, "general msg")
    manager.send_message(agent_id, "alpha msg", session_id="alpha")
    manager.send_message(agent_id, "beta msg", session_id="beta")


def test_list_messages_flag_off_returns_every_row(monkeypatch):
    monkeypatch.setattr(_FLAG_HELPER, lambda: False)
    with tempfile.TemporaryDirectory() as tmpdir:
        manager = AgentManager(db_path=str(Path(tmpdir) / "agents.db"))
        try:
            agent = _new_agent(manager)
            _seed_three(manager, agent["id"])
            msgs = manager.list_messages(agent["id"])
            contents = {m["content"] for m in msgs}
            assert contents == {"general msg", "alpha msg", "beta msg"}
        finally:
            manager.close()


def test_list_messages_flag_on_returns_untagged_only(monkeypatch):
    monkeypatch.setattr(_FLAG_HELPER, lambda: True)
    with tempfile.TemporaryDirectory() as tmpdir:
        manager = AgentManager(db_path=str(Path(tmpdir) / "agents.db"))
        try:
            agent = _new_agent(manager)
            _seed_three(manager, agent["id"])
            msgs = manager.list_messages(agent["id"])
            assert [m["content"] for m in msgs] == ["general msg"]
            assert msgs[0]["session_id"] is None
        finally:
            manager.close()


def test_list_messages_flag_on_include_all_sessions_returns_every_row(monkeypatch):
    monkeypatch.setattr(_FLAG_HELPER, lambda: True)
    with tempfile.TemporaryDirectory() as tmpdir:
        manager = AgentManager(db_path=str(Path(tmpdir) / "agents.db"))
        try:
            agent = _new_agent(manager)
            _seed_three(manager, agent["id"])
            msgs = manager.list_messages(agent["id"], include_all_sessions=True)
            contents = {m["content"] for m in msgs}
            assert contents == {"general msg", "alpha msg", "beta msg"}
        finally:
            manager.close()


def test_list_messages_explicit_session_filters_regardless_of_flag(monkeypatch):
    # Filter works whether the flag is on or off.
    for flag_value in (True, False):
        monkeypatch.setattr(_FLAG_HELPER, lambda v=flag_value: v)
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = AgentManager(db_path=str(Path(tmpdir) / "agents.db"))
            try:
                agent = _new_agent(manager)
                _seed_three(manager, agent["id"])
                msgs = manager.list_messages(agent["id"], session_id="alpha")
                assert [m["content"] for m in msgs] == ["alpha msg"]
                assert msgs[0]["session_id"] == "alpha"
            finally:
                manager.close()
