"""Phase 2F stage 1 — background delegation executor + tool wiring.

Covers the executor in isolation (a fake runtime) and the
``managed_agent_assign_task`` enqueue/inline branch. The
``background_delegation.enabled`` flag defaults off, so the synchronous
path must stay byte-identical to pre-Phase-2F behaviour.
"""

from __future__ import annotations

import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Callable

from openjarvis.agents.manager import AgentManager
from openjarvis.core.config import BackgroundDelegationConfig
from openjarvis.server.background_delegation import (
    BackgroundDelegationExecutor,
    get_background_delegation_executor,
    reset_background_delegation_executor,
)
from openjarvis.server.managed_agent_runtime import (
    ManagedAgentExecutionContext,
    ManagedAgentRuntime,
)
from openjarvis.tools.managed_agent_tools import ManagedAgentAssignTaskTool
from tests.agents.fake_engine import FakeEngine

_HELPER = "openjarvis.tools.managed_agent_tools._background_delegation_config"


def _wait_until(
    predicate: Callable[[], bool], timeout: float = 5.0, interval: float = 0.01
) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()


class _RecordingRuntime:
    """Stand-in for ManagedAgentRuntime — records calls, tracks concurrency."""

    def __init__(
        self,
        *,
        result: str = "ok",
        error: BaseException | None = None,
        gate: threading.Event | None = None,
    ) -> None:
        self.result = result
        self.error = error
        self.gate = gate
        self.calls: list[tuple[str, str, str, tuple[str, ...]]] = []
        self._lock = threading.Lock()
        self.concurrent = 0
        self.max_concurrent = 0

    def run(
        self,
        agent_id: str,
        user_content: str,
        *,
        parent_agent_id: str = "",
        visited_agent_ids: Any = (),
        task_session_id: Any = None,
    ) -> str:
        with self._lock:
            self.concurrent += 1
            self.max_concurrent = max(self.max_concurrent, self.concurrent)
            self.calls.append(
                (agent_id, user_content, parent_agent_id, tuple(visited_agent_ids))
            )
        try:
            if self.gate is not None:
                self.gate.wait(timeout=5.0)
            if self.error is not None:
                raise self.error
            return self.result
        finally:
            with self._lock:
                self.concurrent -= 1


# --- executor unit tests ---------------------------------------------


def test_executor_runs_job_and_reports_result():
    runtime = _RecordingRuntime(result="subordinate done")
    executor = BackgroundDelegationExecutor(max_workers=2)
    seen: list[tuple[Any, Any]] = []
    try:
        executor.submit(
            runtime=runtime,
            agent_id="agent-x",
            kickoff_message="do the work",
            parent_agent_id="chief",
            visited_agent_ids=("chief",),
            on_complete=lambda res, err: seen.append((res, err)),
        )
        assert _wait_until(lambda: len(seen) == 1)
    finally:
        executor.shutdown(timeout=2.0)
    assert seen == [("subordinate done", None)]
    assert runtime.calls == [("agent-x", "do the work", "chief", ("chief",))]


def test_executor_captures_job_exception_and_survives():
    boom = RuntimeError("subordinate blew up")
    runtime = _RecordingRuntime(error=boom)
    executor = BackgroundDelegationExecutor(max_workers=1)
    seen: list[tuple[Any, Any]] = []
    try:
        executor.submit(
            runtime=runtime,
            agent_id="agent-x",
            kickoff_message="m1",
            on_complete=lambda res, err: seen.append((res, err)),
        )
        assert _wait_until(lambda: len(seen) == 1)
        # the worker survived — a second job still runs
        ok_runtime = _RecordingRuntime(result="recovered")
        executor.submit(
            runtime=ok_runtime,
            agent_id="agent-y",
            kickoff_message="m2",
            on_complete=lambda res, err: seen.append((res, err)),
        )
        assert _wait_until(lambda: len(seen) == 2)
    finally:
        executor.shutdown(timeout=2.0)
    assert seen[0] == (None, boom)
    assert seen[1] == ("recovered", None)


def test_executor_bounds_concurrency_to_max_workers():
    gate = threading.Event()
    runtime = _RecordingRuntime(gate=gate)
    executor = BackgroundDelegationExecutor(max_workers=2)
    try:
        for i in range(4):
            executor.submit(
                runtime=runtime,
                agent_id=f"agent-{i}",
                kickoff_message=f"m{i}",
            )
        # exactly max_workers jobs run; the rest queue
        assert _wait_until(lambda: runtime.concurrent == 2)
        time.sleep(0.05)
        assert runtime.concurrent == 2
        gate.set()
        assert _wait_until(lambda: executor.inflight == 0)
    finally:
        gate.set()
        executor.shutdown(timeout=2.0)
    assert runtime.max_concurrent == 2
    assert len(runtime.calls) == 4


# --- tool wiring tests -----------------------------------------------


def _build_ctx(tmpdir: str) -> tuple[Any, Any, Any, Any]:
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
    engine = FakeEngine([{"content": "Worker finished the thing."}])
    runtime = ManagedAgentRuntime(manager, engine, default_model="fake-model")
    return manager, chief, worker, runtime


def test_assign_task_runs_inline_when_flag_off(monkeypatch):
    monkeypatch.setattr(_HELPER, lambda: BackgroundDelegationConfig(enabled=False))
    with tempfile.TemporaryDirectory() as tmpdir:
        manager, chief, worker, runtime = _build_ctx(tmpdir)
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
                description="Do the thing.",
            )
            assert result.success
            assert result.metadata["mode"] == "synchronous"
            assert result.metadata["initial_response"] == "Worker finished the thing."
            assert "Initial response from Worker" in result.content
        finally:
            manager.close()


def test_assign_task_enqueues_when_flag_on(monkeypatch):
    monkeypatch.setattr(
        _HELPER, lambda: BackgroundDelegationConfig(enabled=True, max_workers=2)
    )
    reset_background_delegation_executor()
    with tempfile.TemporaryDirectory() as tmpdir:
        manager, chief, worker, runtime = _build_ctx(tmpdir)
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
                description="Do the thing.",
            )
            # the tool returns immediately — no inline subordinate result
            assert result.success
            assert result.metadata["mode"] == "background"
            assert result.metadata["initial_response"] == ""
            assert "running this task in the background" in result.content

            # the enqueued job runs and the subordinate's reply is stored
            executor = get_background_delegation_executor()
            assert _wait_until(lambda: executor.inflight == 0)
            worker_messages = manager.list_messages(worker["id"])
            assert any(
                m["direction"] == "user_to_agent"
                and "Do the thing." in m["content"]
                for m in worker_messages
            )
            assert any(
                m["direction"] == "agent_to_user"
                and "Worker finished the thing." in m["content"]
                for m in worker_messages
            )
            # Stage 2 — the upward return path: the chief's log gets a
            # completion notice carrying the subordinate's result.
            chief_messages = manager.list_messages(chief["id"])
            assert any(
                m["direction"] == "user_to_agent"
                and m["mode"] == "delegated"
                and "delegated to Worker" in m["content"]
                and "finished" in m["content"]
                and "Worker finished the thing." in m["content"]
                for m in chief_messages
            )
        finally:
            reset_background_delegation_executor()
            manager.close()


def test_assign_task_background_failure_notifies_parent(monkeypatch):
    """Stage 2 — a failed background turn still rolls back up to the parent."""
    monkeypatch.setattr(
        _HELPER, lambda: BackgroundDelegationConfig(enabled=True)
    )
    reset_background_delegation_executor()
    with tempfile.TemporaryDirectory() as tmpdir:
        manager, chief, worker, _real_runtime = _build_ctx(tmpdir)
        # Swap in a fake runtime whose run() raises — we want the
        # callback to receive the error path.
        failing_runtime = _RecordingRuntime(error=RuntimeError("subordinate blew up"))
        try:
            ctx = ManagedAgentExecutionContext(
                runtime=failing_runtime,
                manager=manager,
                engine=None,
                current_agent_id=chief["id"],
            )
            tool = ManagedAgentAssignTaskTool(context=ctx)
            result = tool.execute(
                agent_name_or_id="Worker",
                description="This one will fail.",
            )
            assert result.success
            assert result.metadata["mode"] == "background"

            executor = get_background_delegation_executor()
            assert _wait_until(lambda: executor.inflight == 0)
            assert failing_runtime.calls  # the worker pool did invoke run()
            chief_messages = manager.list_messages(chief["id"])
            assert any(
                m["direction"] == "user_to_agent"
                and m["mode"] == "delegated"
                and "delegated to Worker" in m["content"]
                and "failed" in m["content"]
                and "subordinate blew up" in m["content"]
                for m in chief_messages
            )
        finally:
            reset_background_delegation_executor()
            manager.close()


def test_assign_task_loop_guard_blocks_before_enqueue(monkeypatch):
    monkeypatch.setattr(
        _HELPER, lambda: BackgroundDelegationConfig(enabled=True)
    )
    reset_background_delegation_executor()
    with tempfile.TemporaryDirectory() as tmpdir:
        manager, chief, worker, runtime = _build_ctx(tmpdir)
        try:
            # the target already appears in the delegation path
            ctx = ManagedAgentExecutionContext(
                runtime=runtime,
                manager=manager,
                engine=runtime._engine,
                current_agent_id=chief["id"],
                visited_agent_ids=(worker["id"],),
            )
            tool = ManagedAgentAssignTaskTool(context=ctx)
            result = tool.execute(
                agent_name_or_id="Worker",
                description="Do the thing.",
            )
            assert result.success
            assert result.metadata["mode"] == "skipped"
            assert "delegation loop" in result.metadata["initial_response"]
            assert get_background_delegation_executor().inflight == 0
        finally:
            reset_background_delegation_executor()
            manager.close()


def test_assign_task_depth_guard_blocks_before_enqueue(monkeypatch):
    monkeypatch.setattr(
        _HELPER, lambda: BackgroundDelegationConfig(enabled=True)
    )
    reset_background_delegation_executor()
    with tempfile.TemporaryDirectory() as tmpdir:
        manager, chief, worker, runtime = _build_ctx(tmpdir)
        try:
            # 5 prior hops + the current agent == depth 6, the limit
            ctx = ManagedAgentExecutionContext(
                runtime=runtime,
                manager=manager,
                engine=runtime._engine,
                current_agent_id=chief["id"],
                visited_agent_ids=("a1", "a2", "a3", "a4", "a5"),
            )
            tool = ManagedAgentAssignTaskTool(context=ctx)
            result = tool.execute(
                agent_name_or_id="Worker",
                description="Do the thing.",
            )
            assert result.success
            assert result.metadata["mode"] == "skipped"
            assert "depth limit" in result.metadata["initial_response"]
            assert get_background_delegation_executor().inflight == 0
        finally:
            reset_background_delegation_executor()
            manager.close()
