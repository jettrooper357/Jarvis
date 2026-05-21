"""Hierarchical trace tests for ManagedAgentRuntime.

Validates that a single user request through a chief in chief mode
produces a trace tree:

    chief root
      |-- worker A (parent_trace_id = chief root)
      |-- worker B (parent_trace_id = chief root)

All three traces share the same run_id.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any, Dict, List

import pytest

from openjarvis.agents.manager import AgentManager
from openjarvis.server.managed_agent_runtime import ManagedAgentRuntime
from openjarvis.traces.store import TraceStore
from tests.agents.fake_engine import FakeEngine


# ---------------------------------------------------------------------------
# Test environment
# ---------------------------------------------------------------------------


class _StubProjectStore:
    """Minimal project store that satisfies AgentManager's hard-link rules.

    Every agent task is required to point at a project task; this stub
    returns a single dummy task for any lookup and lets create_task /
    create_project pass through as no-ops.
    """

    _DUMMY_TASK: Dict[str, Any] = {
        "id": "proj_task_dummy",
        "project_id": "proj_dummy",
        "title": "Dummy",
        "parent_task_id": None,
        "status": "Backlog",
    }
    _DUMMY_PROJECT: Dict[str, Any] = {"id": "proj_dummy", "name": "Dummy"}

    def get_task(self, task_id: str) -> Dict[str, Any]:
        return dict(self._DUMMY_TASK, id=task_id)

    def list_tasks(self, project_id: str) -> List[Dict[str, Any]]:
        return [dict(self._DUMMY_TASK)]

    def list_projects(self) -> List[Dict[str, Any]]:
        return [dict(self._DUMMY_PROJECT)]

    def get_project(self, project_id: str) -> Dict[str, Any]:
        return dict(self._DUMMY_PROJECT)

    def create_project(self, **kwargs: Any) -> Dict[str, Any]:
        return dict(self._DUMMY_PROJECT)

    def create_task(self, project_id: str, **kwargs: Any) -> Dict[str, Any]:
        out = dict(self._DUMMY_TASK)
        out["project_id"] = project_id
        return out

    def update_task(self, task_id: str, **kwargs: Any) -> Dict[str, Any]:
        return dict(self._DUMMY_TASK, id=task_id, **kwargs)


@pytest.fixture
def runtime_env(tmp_path: Path):
    agents_db = tmp_path / "agents.db"
    traces_db = tmp_path / "traces.db"
    manager = AgentManager(
        db_path=str(agents_db),
        project_store=_StubProjectStore(),
    )
    trace_store = TraceStore(str(traces_db))

    chief = manager.create_agent(
        name="Test Chief",
        agent_type="monitor_operative",
        org_role="chief orchestrator",
        config={
            "model": "fake-model",
            "orchestrator_mode": "chief",
            "max_turns": 3,
            "temperature": 0.0,
            "max_tokens": 256,
        },
    )
    worker_a = manager.create_agent(
        name="Test Worker A",
        agent_type="monitor_operative",
        org_role="researcher",
        config={
            "model": "fake-model",
            "system_prompt": "You are a researcher.",
            "max_turns": 1,
            "temperature": 0.0,
            "max_tokens": 128,
        },
        manager_agent_id=chief["id"],
    )
    worker_b = manager.create_agent(
        name="Test Worker B",
        agent_type="monitor_operative",
        org_role="researcher",
        config={
            "model": "fake-model",
            "system_prompt": "You are a researcher.",
            "max_turns": 1,
            "temperature": 0.0,
            "max_tokens": 128,
        },
        manager_agent_id=chief["id"],
    )

    yield {
        "manager": manager,
        "trace_store": trace_store,
        "chief": chief,
        "worker_a": worker_a,
        "worker_b": worker_b,
        "tmp_path": tmp_path,
    }

    manager.close()
    trace_store.close()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_root_run_writes_trace_with_no_parent(runtime_env):
    """A user-initiated managed-agent run writes a Trace with parent_trace_id=None."""
    engine = FakeEngine(
        [
            {
                "content": json.dumps(
                    {
                        "action": "complete",
                        "reason": "direct",
                        "final_report": {
                            "status": "completed",
                            "summary": "ok",
                        },
                    }
                ),
            },
        ]
    )
    runtime = ManagedAgentRuntime(
        runtime_env["manager"],
        engine,
        trace_store=runtime_env["trace_store"],
        default_model="fake-model",
    )

    runtime.run(runtime_env["chief"]["id"], "Status check.")

    traces = runtime_env["trace_store"]._fetchall()
    assert len(traces) == 1
    trace = runtime_env["trace_store"]._row_to_trace(traces[0])
    assert trace.parent_trace_id is None
    assert trace.run_id == trace.trace_id  # root uses own id as run_id
    assert trace.agent == runtime_env["chief"]["id"]
    assert trace.outcome == "success"


def test_chief_with_two_workers_produces_trace_tree(runtime_env):
    """Chief delegates to two workers; all three traces form one tree."""
    chief_id = runtime_env["chief"]["id"]
    worker_a_id = runtime_env["worker_a"]["id"]
    worker_b_id = runtime_env["worker_b"]["id"]

    delegate_response = {
        "content": json.dumps(
            {
                "action": "delegate",
                "reason": "Two parallel research tasks.",
                "delegations": [
                    {
                        "agent_name_or_id": worker_a_id,
                        "message": "Research Prometheus.",
                    },
                    {
                        "agent_name_or_id": worker_b_id,
                        "message": "Research Datadog.",
                    },
                ],
            }
        ),
    }
    complete_response = {
        "content": json.dumps(
            {
                "action": "complete",
                "reason": "Synthesized.",
                "final_report": {
                    "status": "completed",
                    "summary": "Recommendation: Prometheus.",
                },
            }
        ),
    }
    worker_a_response = {"content": "Prometheus is solid."}
    worker_b_response = {"content": "Datadog is comprehensive."}

    engine = FakeEngine(
        [
            delegate_response,    # chief turn 1
            worker_a_response,    # worker A turn
            worker_b_response,    # worker B turn
            complete_response,    # chief turn 2 (aggregate)
        ]
    )
    runtime = ManagedAgentRuntime(
        runtime_env["manager"],
        engine,
        trace_store=runtime_env["trace_store"],
        default_model="fake-model",
    )

    runtime.run(chief_id, "Compare Prometheus and Datadog.")

    store = runtime_env["trace_store"]
    traces = [store._row_to_trace(r) for r in store._fetchall()]
    assert len(traces) == 3, f"expected 3 traces, got {len(traces)}"

    chief_traces = [t for t in traces if t.agent == chief_id]
    assert len(chief_traces) == 1
    chief_trace = chief_traces[0]
    assert chief_trace.parent_trace_id is None
    assert chief_trace.run_id == chief_trace.trace_id

    worker_traces = [t for t in traces if t.agent != chief_id]
    assert len(worker_traces) == 2
    for wt in worker_traces:
        assert wt.parent_trace_id == chief_trace.trace_id, (
            f"worker {wt.agent} has parent_trace_id={wt.parent_trace_id!r}, "
            f"expected chief id {chief_trace.trace_id!r}"
        )
        assert wt.run_id == chief_trace.run_id

    children = store.list_children(chief_trace.trace_id)
    assert len(children) == 2
    by_run = store.list_by_run(chief_trace.run_id)
    assert len(by_run) == 3


def test_chief_dedupes_identical_delegations_in_one_action(runtime_env):
    """A chief that emits the same (target, message) twice runs it once."""
    chief_id = runtime_env["chief"]["id"]
    worker_a_id = runtime_env["worker_a"]["id"]

    captured: list = []

    def fake_delegate(agent_id: str, message: str, *, tools_allowed=None):
        captured.append(agent_id)
        return "ok"

    # Two identical delegations in one action.
    delegate_response = {
        "content": json.dumps(
            {
                "action": "delegate",
                "reason": "duplicate target",
                "delegations": [
                    {"agent_name_or_id": worker_a_id, "message": "Do X."},
                    {"agent_name_or_id": worker_a_id, "message": "Do X."},
                ],
            }
        )
    }
    complete_response = {
        "content": json.dumps(
            {
                "action": "complete",
                "reason": "done",
                "final_report": {"status": "completed", "summary": "ok"},
            }
        )
    }
    engine = FakeEngine([delegate_response, complete_response])

    # Build the chief directly with an injected delegate_fn so the
    # dedupe is exercised at the OrchestratorAgent layer.
    from openjarvis.agents.orchestrator import OrchestratorAgent

    chief = OrchestratorAgent(
        engine=engine,
        model="fake-model",
        mode="chief",
        max_turns=4,
        delegate_fn=fake_delegate,
    )
    chief.run("Do X.")
    # Only ONE delegation should have fired despite the chief listing two.
    assert len(captured) == 1


def test_standard_turn_dedupes_identical_tool_calls(runtime_env):
    """A subordinate that calls the same tool twice with same args sees the cached result."""
    from openjarvis.core.types import ToolResult
    from openjarvis.tools._stubs import BaseTool, ToolSpec

    invoke_count: list = []

    class _CounterTool(BaseTool):
        tool_id = "counter_tool"

        @property
        def spec(self) -> ToolSpec:
            return ToolSpec(
                name="counter_tool",
                description="Counts invocations.",
                parameters={
                    "type": "object",
                    "properties": {"x": {"type": "string"}},
                },
            )

        def execute(self, **params) -> ToolResult:
            invoke_count.append(params)
            return ToolResult(
                tool_name="counter_tool",
                content=f"ran #{len(invoke_count)}",
                success=True,
            )

    # Subordinate emits TWO identical tool calls in one turn, then a
    # final text response. Without dedupe the tool would run twice.
    duplicate_call = {
        "id": "tc_a",
        "name": "counter_tool",
        "arguments": '{"x":"same"}',
    }
    first_turn = {
        "content": "",
        "tool_calls": [
            duplicate_call,
            {**duplicate_call, "id": "tc_b"},  # same args, different id
        ],
    }
    final_turn = {"content": "done."}
    engine = FakeEngine([first_turn, final_turn])

    manager = runtime_env["manager"]
    worker = manager.create_agent(
        name="Counter Worker",
        agent_type="monitor_operative",
        org_role="researcher",
        config={
            "model": "fake-model",
            "system_prompt": "You count.",
            "tools": ["counter_tool"],
            "max_turns": 2,
        },
    )

    # Patch the tool registry so build_agent_tool_instances finds counter_tool.
    from openjarvis.core.registry import ToolRegistry

    ToolRegistry.register("counter_tool")(_CounterTool)

    runtime = ManagedAgentRuntime(
        manager, engine, default_model="fake-model",
        trace_store=runtime_env["trace_store"],
    )
    try:
        runtime.run(worker["id"], "Use the counter.")
    finally:
        # Clean up registry to avoid polluting other tests.
        try:
            ToolRegistry._entries().pop("counter_tool", None)
        except Exception:
            pass

    # The tool's execute() should have run exactly ONCE despite two
    # tool_calls being emitted with identical arguments.
    assert len(invoke_count) == 1, (
        f"expected exactly one underlying execute(); got {len(invoke_count)}"
    )


def test_standard_turn_caps_project_create_task_at_one_per_turn(runtime_env):
    """The semantic cap blocks a second project_create_task with different args.

    Reproduces the "model creates one messy-title task plus one clean one"
    bug: the args-based dedupe alone cannot catch this because the args
    differ. The semantic cap blocks the second create unless the request
    explicitly listed multiple tasks.
    """
    from openjarvis.core.types import ToolResult
    from openjarvis.tools._stubs import BaseTool, ToolSpec

    invoke_args: list = []

    class _FakeProjectCreateTaskTool(BaseTool):
        tool_id = "project_create_task"

        @property
        def spec(self) -> ToolSpec:
            return ToolSpec(
                name="project_create_task",
                description="Create a task.",
                parameters={
                    "type": "object",
                    "properties": {
                        "project_id": {"type": "string"},
                        "title": {"type": "string"},
                    },
                    "required": ["project_id", "title"],
                },
            )

        def execute(self, **params) -> ToolResult:
            invoke_args.append(params)
            return ToolResult(
                tool_name="project_create_task",
                content=f"task_{len(invoke_args)}",
                success=True,
            )

    # Model emits two project_create_task calls in one turn with
    # different titles (the exact bug pattern).
    first_turn = {
        "content": "",
        "tool_calls": [
            {
                "id": "tc_a",
                "name": "project_create_task",
                "arguments": json.dumps(
                    {
                        "project_id": "proj_dummy",
                        "title": (
                            "release a new song called Raise One for the Old "
                            "Guard. Acceptance criteria: - Task is created"
                        ),
                    }
                ),
            },
            {
                "id": "tc_b",
                "name": "project_create_task",
                "arguments": json.dumps(
                    {
                        "project_id": "proj_dummy",
                        "title": "Raise One for the Old Guard",
                    }
                ),
            },
        ],
    }
    final_turn = {"content": "done."}
    engine = FakeEngine([first_turn, final_turn])

    manager = runtime_env["manager"]
    worker = manager.create_agent(
        name="Test WM",
        agent_type="monitor_operative",
        org_role="workflow manager",
        config={
            "model": "fake-model",
            "system_prompt": "You manage projects.",
            "tools": ["project_create_task"],
            "max_turns": 2,
        },
    )

    from openjarvis.core.registry import ToolRegistry

    original = ToolRegistry._entries().get("project_create_task")
    ToolRegistry._entries()["project_create_task"] = _FakeProjectCreateTaskTool

    runtime = ManagedAgentRuntime(
        manager, engine, default_model="fake-model",
        trace_store=runtime_env["trace_store"],
    )
    try:
        runtime.run(worker["id"], "add a task to release a new song called Raise One for the Old Guard")
    finally:
        if original is not None:
            ToolRegistry._entries()["project_create_task"] = original
        else:
            ToolRegistry._entries().pop("project_create_task", None)

    assert len(invoke_args) == 1, (
        "expected the cap to block the second project_create_task; got "
        f"{len(invoke_args)} invocations"
    )


def test_standard_turn_allows_multiple_tasks_when_user_lists_them(runtime_env):
    """The cap lifts when the user message has an explicit multi-task signal."""
    from openjarvis.core.types import ToolResult
    from openjarvis.tools._stubs import BaseTool, ToolSpec

    invoke_args: list = []

    class _FakeProjectCreateTaskTool(BaseTool):
        tool_id = "project_create_task"

        @property
        def spec(self) -> ToolSpec:
            return ToolSpec(
                name="project_create_task",
                description="Create a task.",
                parameters={
                    "type": "object",
                    "properties": {
                        "project_id": {"type": "string"},
                        "title": {"type": "string"},
                    },
                    "required": ["project_id", "title"],
                },
            )

        def execute(self, **params) -> ToolResult:
            invoke_args.append(params)
            return ToolResult(
                tool_name="project_create_task",
                content=f"task_{len(invoke_args)}",
                success=True,
            )

    first_turn = {
        "content": "",
        "tool_calls": [
            {
                "id": "tc_a",
                "name": "project_create_task",
                "arguments": json.dumps(
                    {"project_id": "proj_dummy", "title": "Alpha"}
                ),
            },
            {
                "id": "tc_b",
                "name": "project_create_task",
                "arguments": json.dumps(
                    {"project_id": "proj_dummy", "title": "Beta"}
                ),
            },
        ],
    }
    final_turn = {"content": "done."}
    engine = FakeEngine([first_turn, final_turn])

    manager = runtime_env["manager"]
    worker = manager.create_agent(
        name="Test WM Multi",
        agent_type="monitor_operative",
        org_role="workflow manager",
        config={
            "model": "fake-model",
            "system_prompt": "You manage projects.",
            "tools": ["project_create_task"],
            "max_turns": 2,
        },
    )

    from openjarvis.core.registry import ToolRegistry

    original = ToolRegistry._entries().get("project_create_task")
    ToolRegistry._entries()["project_create_task"] = _FakeProjectCreateTaskTool

    runtime = ManagedAgentRuntime(
        manager, engine, default_model="fake-model",
        trace_store=runtime_env["trace_store"],
    )
    try:
        runtime.run(
            worker["id"],
            "create two tasks: Alpha and Beta",
        )
    finally:
        if original is not None:
            ToolRegistry._entries()["project_create_task"] = original
        else:
            ToolRegistry._entries().pop("project_create_task", None)

    assert len(invoke_args) == 2, (
        "expected both project_create_task calls to run when the user "
        f"explicitly listed two tasks; got {len(invoke_args)}"
    )


def test_materialize_skipped_when_agent_successfully_delegated(runtime_env):
    """The materialize fallback must NOT fire when the agent already
    delegated the work to a subordinate.

    This is the root of the "two tasks from one request" bug: the chief's
    own tool_calls only contain managed_agent_delegate, not the inner
    project_create_task that the subordinate ran. Without the delegate
    skip, the chief's runtime.run would parse the user message and
    materialize a duplicate task at the chief level.
    """
    from openjarvis.server.managed_agent_runtime import ManagedAgentRuntime

    manager = runtime_env["manager"]

    create_calls: list = []

    class _SpyStore(_StubProjectStore):  # type: ignore[misc]
        def create_task(self, project_id, **kwargs):
            create_calls.append({"project_id": project_id, **kwargs})
            return super().create_task(project_id, **kwargs)

        def list_projects(self):
            return [{"id": "iron_saints", "name": "Iron Saints"}]

        def list_tasks(self, project_id):
            return []

    manager._project_store = lambda: _SpyStore()  # type: ignore[method-assign]

    chief_record = runtime_env["chief"]
    manager.update_agent(
        chief_record["id"],
        config_patch={
            "tools": ["project_create_task", "managed_agent_delegate"],
        },
    )

    runtime = ManagedAgentRuntime(
        manager,
        FakeEngine([]),
        default_model="fake-model",
        trace_store=runtime_env["trace_store"],
    )

    chief_after = manager.get_agent(chief_record["id"])
    materialized = runtime._maybe_materialize_project_task_request(
        agent_record=chief_after,
        user_content=(
            "add a task to release a new song called Raise One for the Old "
            "Guard to the Iron Saints project"
        ),
        response_text="Delegated.",
        tool_calls=[
            {
                "tool": "managed_agent_delegate",
                "arguments": "{}",
                "result": "WM handled it",
                "success": True,
            }
        ],
    )

    assert materialized is None, (
        "materialize must NOT fire when the agent delegated successfully; "
        "doing so creates a duplicate task at the chief level"
    )
    assert create_calls == [], (
        "no task should have been created by the chief-level materialize"
    )


def test_waiting_on_tool_status_during_chief_tool_call(runtime_env):
    """While a chief's tool call is in flight, status flips to waiting_on_tool."""
    chief_id = runtime_env["chief"]["id"]
    worker_a_id = runtime_env["worker_a"]["id"]
    manager = runtime_env["manager"]

    captured_chief_status: list = []

    class _StatusCapturingEngine(FakeEngine):
        """Records the chief's status at every engine.generate call."""

        def __init__(self, responses):
            super().__init__(responses)
            self._mgr = manager
            self._chief_id = chief_id

        def generate(self, messages, **kw):
            try:
                rec = self._mgr.get_agent(self._chief_id)
                captured_chief_status.append(
                    (rec.get("status"), rec.get("current_activity"))
                )
            except Exception:
                captured_chief_status.append(("?", ""))
            return super().generate(messages, **kw)

    delegate_response = {
        "content": json.dumps(
            {
                "action": "delegate",
                "reason": "Send to specialist.",
                "delegations": [
                    {
                        "agent_name_or_id": worker_a_id,
                        "message": "Research X.",
                    }
                ],
            }
        ),
    }
    complete_response = {
        "content": json.dumps(
            {
                "action": "complete",
                "reason": "Worker replied.",
                "final_report": {"status": "completed", "summary": "ok"},
            }
        ),
    }
    worker_response = {"content": "X is fine."}

    engine = _StatusCapturingEngine(
        [delegate_response, worker_response, complete_response]
    )
    runtime = ManagedAgentRuntime(
        manager, engine,
        trace_store=runtime_env["trace_store"], default_model="fake-model",
    )

    runtime.run(chief_id, "Investigate X.")

    # Sequence: chief decide -> worker generate (chief should be waiting_on_tool) -> chief aggregate
    assert len(captured_chief_status) == 3
    chief_decide_status = captured_chief_status[0]
    worker_call_status = captured_chief_status[1]
    chief_aggregate_status = captured_chief_status[2]

    # When the worker's engine fires, the chief is parked on the
    # managed_agent_delegate tool call.
    assert worker_call_status[0] == "waiting_on_tool", (
        f"expected waiting_on_tool, got {worker_call_status}"
    )
    assert worker_call_status[1].startswith("tool: managed_agent_delegate"), (
        f"expected current_activity to name the tool, got {worker_call_status[1]!r}"
    )

    # Before any tool fires, the chief is just running.
    assert chief_decide_status[0] in ("running", "idle"), chief_decide_status
    # After the tool returns, status reverts.
    assert chief_aggregate_status[0] == "running", chief_aggregate_status


def test_failed_root_run_still_writes_trace(runtime_env):
    """A run that raises records an error-outcome trace, not silent loss."""
    engine = FakeEngine(
        [
            {"content": "this is not valid JSON for the chief"},
            {"content": "still nonsense"},
        ]
    )
    runtime = ManagedAgentRuntime(
        runtime_env["manager"],
        engine,
        trace_store=runtime_env["trace_store"],
        default_model="fake-model",
    )

    # The chief stops after one repair turn; result is user-facing,
    # not an exception. Trace still gets written with outcome="success"
    # because the runtime considers a returned string a normal completion.
    runtime.run(runtime_env["chief"]["id"], "Whatever.")

    traces = runtime_env["trace_store"]._fetchall()
    assert len(traces) == 1
