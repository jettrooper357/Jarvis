"""Phase 2G stage 2 — worker session isolation end-to-end.

Delegated turns are scoped to their per-task session: the worker's writes
are tagged, its history read is filtered, two concurrent background
delegations against the same worker don't interleave, and the Phase 2F
parent-notification still posts a roll-up to the parent's log. Merge +
fork events fire when the bus is wired.
"""

from __future__ import annotations

import tempfile
import time
from pathlib import Path
from typing import Any, Callable

from openjarvis.agents.manager import AgentManager
from openjarvis.core.config import BackgroundDelegationConfig
from openjarvis.core.events import EventBus, EventType
from openjarvis.server.background_delegation import (
    get_background_delegation_executor,
    reset_background_delegation_executor,
)
from openjarvis.server.managed_agent_runtime import (
    ManagedAgentExecutionContext,
    ManagedAgentRuntime,
)
from openjarvis.tools.managed_agent_tools import ManagedAgentAssignTaskTool
from tests.agents.fake_engine import FakeEngine

_BG_HELPER = "openjarvis.tools.managed_agent_tools._background_delegation_config"
_TOOL_ISO_HELPER = (
    "openjarvis.tools.managed_agent_tools._worker_session_isolation_enabled"
)
_RUNTIME_ISO_HELPER = (
    "openjarvis.server.managed_agent_runtime._worker_session_isolation_enabled"
)
_MANAGER_ISO_HELPER = (
    "openjarvis.agents.manager._worker_session_isolation_enabled"
)


def _enable_isolation(monkeypatch) -> None:
    monkeypatch.setattr(_TOOL_ISO_HELPER, lambda: True)
    monkeypatch.setattr(_RUNTIME_ISO_HELPER, lambda: True)
    monkeypatch.setattr(_MANAGER_ISO_HELPER, lambda: True)


def _wait_until(
    predicate: Callable[[], bool], timeout: float = 5.0, interval: float = 0.01
) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()


def _build(
    tmpdir: str, *, worker_response: str = "Worker finished.", bus: Any = None
) -> tuple[Any, Any, Any, Any]:
    manager = AgentManager(db_path=str(Path(tmpdir) / "agents.db"))
    chief = manager.create_agent(
        name="Chief",
        agent_type="deep_research",
        org_role="Chief Executive Officer (CEO)",
        config={"max_turns": 4},
    )
    worker = manager.create_agent(
        name="Worker",
        agent_type="simple",
        org_role="Worker",
        manager_agent_id=chief["id"],
        config={"system_prompt": "You do assigned work."},
    )
    engine = FakeEngine([{"content": worker_response}])
    runtime = ManagedAgentRuntime(
        manager, engine, default_model="fake-model", bus=bus
    )
    return manager, chief, worker, runtime


# --- inline (synchronous) delegation tags messages and emits FORKED ---


def test_sync_delegation_with_isolation_tags_messages_and_persists_task(
    monkeypatch,
):
    """Flag on + synchronous delegation: worker writes are tagged; the
    owning task carries the session id; history loader scopes correctly."""
    _enable_isolation(monkeypatch)
    monkeypatch.setattr(_BG_HELPER, lambda: BackgroundDelegationConfig(enabled=False))
    bus = EventBus()
    forks: list[dict] = []
    bus.subscribe(
        EventType.AGENT_SESSION_FORKED,
        lambda evt: forks.append(dict(evt.data)),
    )
    with tempfile.TemporaryDirectory() as tmpdir:
        manager, chief, worker, runtime = _build(tmpdir, bus=bus)
        try:
            # Pre-seed the worker's *general* session with an unrelated
            # message so we can prove isolation hides it from the
            # delegated turn.
            manager.send_message(worker["id"], "unrelated chatter")

            ctx = ManagedAgentExecutionContext(
                runtime=runtime,
                manager=manager,
                engine=runtime._engine,
                current_agent_id=chief["id"],
            )
            tool = ManagedAgentAssignTaskTool(context=ctx)
            result = tool.execute(
                agent_name_or_id="Worker",
                description="Do the scoped thing.",
            )
            assert result.success
            assert result.metadata["mode"] == "synchronous"

            # The task row carries the minted session id.
            task_id = result.metadata["task_id"]
            task = manager._get_task(task_id)
            assert task is not None
            session_id = str(task.get("task_session_id") or "")
            assert session_id, "expected a worker session id on the task"

            # FORKED fired with the right payload.
            assert len(forks) == 1
            assert forks[0]["session_id"] == session_id
            assert forks[0]["task_id"] == task_id
            assert forks[0]["worker_agent_id"] == worker["id"]
            assert forks[0]["parent_agent_id"] == chief["id"]

            # Worker's tagged messages exist and the general unrelated
            # chatter is NOT in the scoped read.
            scoped = manager.list_messages(
                worker["id"], session_id=session_id
            )
            scoped_contents = {m["content"] for m in scoped}
            assert "unrelated chatter" not in scoped_contents
            assert any(
                "Do the scoped thing." in m["content"]
                and m["direction"] == "user_to_agent"
                for m in scoped
            )
            assert any(
                "Worker finished." in m["content"]
                and m["direction"] == "agent_to_user"
                for m in scoped
            )

            # Untagged general session still only has the pre-seeded msg.
            untagged = manager.list_messages(worker["id"])
            assert [m["content"] for m in untagged] == ["unrelated chatter"]

            # The audit hatch shows everything.
            full = manager.list_messages(
                worker["id"], include_all_sessions=True
            )
            full_contents = {m["content"] for m in full}
            assert {
                "unrelated chatter",
                "Worker finished.",
            }.issubset(full_contents)
        finally:
            manager.close()


# --- background path: tagging + parent notification + merge event ----


def test_background_delegation_with_isolation_tags_and_emits_merge(monkeypatch):
    _enable_isolation(monkeypatch)
    monkeypatch.setattr(
        _BG_HELPER, lambda: BackgroundDelegationConfig(enabled=True, max_workers=2)
    )
    reset_background_delegation_executor()
    bus = EventBus()
    forks: list[dict] = []
    merges: list[dict] = []
    bus.subscribe(
        EventType.AGENT_SESSION_FORKED,
        lambda evt: forks.append(dict(evt.data)),
    )
    bus.subscribe(
        EventType.AGENT_SESSION_MERGED,
        lambda evt: merges.append(dict(evt.data)),
    )
    with tempfile.TemporaryDirectory() as tmpdir:
        manager, chief, worker, runtime = _build(tmpdir, bus=bus)
        try:
            ctx = ManagedAgentExecutionContext(
                runtime=runtime,
                manager=manager,
                engine=runtime._engine,
                current_agent_id=chief["id"],
            )
            tool = ManagedAgentAssignTaskTool(context=ctx)
            result = tool.execute(
                agent_name_or_id="Worker",
                description="Do the scoped thing in the background.",
            )
            assert result.metadata["mode"] == "background"
            assert _wait_until(
                lambda: get_background_delegation_executor().inflight == 0
            )

            task_id = result.metadata["task_id"]
            task = manager._get_task(task_id)
            session_id = str((task or {}).get("task_session_id") or "")
            assert session_id

            # Scoped read carries the worker's tagged exchange.
            scoped = manager.list_messages(
                worker["id"], session_id=session_id
            )
            assert any(
                "Do the scoped thing in the background." in m["content"]
                for m in scoped
            )
            assert any(
                "Worker finished." in m["content"]
                and m["direction"] == "agent_to_user"
                for m in scoped
            )

            # The Phase 2F parent notification landed in the chief's log
            # (in the *general* session — not tagged with the worker's id).
            chief_msgs = manager.list_messages(
                chief["id"], include_all_sessions=True
            )
            assert any(
                m["mode"] == "delegated"
                and "delegated to Worker" in m["content"]
                and "finished" in m["content"]
                and m["session_id"] is None
                for m in chief_msgs
            )

            # Stage 2 — fork and merge events fired exactly once.
            assert len(forks) == 1 and forks[0]["session_id"] == session_id
            assert len(merges) == 1 and merges[0]["session_id"] == session_id
            assert merges[0]["task_id"] == task_id
        finally:
            reset_background_delegation_executor()
            manager.close()


# --- parallel safety: two concurrent delegations don't interleave ----


def test_two_concurrent_background_delegations_do_not_interleave(monkeypatch):
    _enable_isolation(monkeypatch)
    monkeypatch.setattr(
        _BG_HELPER, lambda: BackgroundDelegationConfig(enabled=True, max_workers=2)
    )
    reset_background_delegation_executor()
    with tempfile.TemporaryDirectory() as tmpdir:
        manager = AgentManager(db_path=str(Path(tmpdir) / "agents.db"))
        chief = manager.create_agent(
            name="Chief",
            agent_type="deep_research",
            org_role="Chief Executive Officer (CEO)",
            config={"max_turns": 4},
        )
        worker = manager.create_agent(
            name="Worker",
            agent_type="simple",
            org_role="Worker",
            manager_agent_id=chief["id"],
            config={"system_prompt": "You do assigned work."},
        )
        # The FakeEngine clamps to the last response, so every call
        # returns the same string — perfect for proving each delegation
        # writes into its OWN session, not a shared bucket.
        engine = FakeEngine(
            [{"content": "Worker reply for whichever task asked."}]
        )
        runtime = ManagedAgentRuntime(manager, engine, default_model="fake-model")
        try:
            ctx = ManagedAgentExecutionContext(
                runtime=runtime,
                manager=manager,
                engine=engine,
                current_agent_id=chief["id"],
            )
            tool = ManagedAgentAssignTaskTool(context=ctx)
            r1 = tool.execute(
                agent_name_or_id="Worker",
                description="Task ALPHA: investigate alpha topic.",
            )
            r2 = tool.execute(
                agent_name_or_id="Worker",
                description="Task BETA: investigate beta topic.",
            )
            assert r1.metadata["mode"] == "background"
            assert r2.metadata["mode"] == "background"
            assert _wait_until(
                lambda: get_background_delegation_executor().inflight == 0
            )

            alpha_task = manager._get_task(r1.metadata["task_id"])
            beta_task = manager._get_task(r2.metadata["task_id"])
            alpha_session = str(alpha_task["task_session_id"])
            beta_session = str(beta_task["task_session_id"])
            assert alpha_session and beta_session
            assert alpha_session != beta_session

            alpha_msgs = manager.list_messages(
                worker["id"], session_id=alpha_session
            )
            beta_msgs = manager.list_messages(
                worker["id"], session_id=beta_session
            )
            alpha_kickoff = next(
                m for m in alpha_msgs if m["direction"] == "user_to_agent"
            )
            beta_kickoff = next(
                m for m in beta_msgs if m["direction"] == "user_to_agent"
            )
            assert "ALPHA" in alpha_kickoff["content"]
            assert "BETA" not in alpha_kickoff["content"]
            assert "BETA" in beta_kickoff["content"]
            assert "ALPHA" not in beta_kickoff["content"]
        finally:
            reset_background_delegation_executor()
            manager.close()


# --- audit hatch: the runtime hatch unchanged when flag off -----------


def test_flag_off_runtime_is_byte_identical(monkeypatch):
    """With the flag off, ``run()`` does not tag messages even if a
    ``task_session_id`` is supplied — byte-identical to pre-Phase-2G."""
    monkeypatch.setattr(_RUNTIME_ISO_HELPER, lambda: False)
    monkeypatch.setattr(_MANAGER_ISO_HELPER, lambda: False)
    with tempfile.TemporaryDirectory() as tmpdir:
        manager, chief, worker, runtime = _build(tmpdir)
        try:
            runtime.run(
                worker["id"],
                "Hello worker.",
                parent_agent_id=chief["id"],
                task_session_id="would-be-session",
            )
            rows = manager._conn.execute(
                "SELECT direction, content, session_id FROM agent_messages"
                " WHERE agent_id = ? ORDER BY created_at",
                (worker["id"],),
            ).fetchall()
            assert len(rows) == 2
            assert all(r["session_id"] is None for r in rows)
        finally:
            manager.close()
