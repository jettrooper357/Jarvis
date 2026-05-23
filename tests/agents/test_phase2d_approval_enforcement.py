"""Phase 2D enforcement (stage 1) — the tool-dispatch approval gate.

Covers ``ManagedAgentRuntime._approval_gate`` and the single-use
``ApprovalStore`` helpers it relies on. The gate is a transparent no-op
unless an ``ApprovalStore`` is wired, ``approval_gating.enabled`` is set,
and the tool is listed in the agent's ``requires_approval_tools`` axis.

See ``docs/CHANGE_IMPACT_NOTICES/approval-enforcement-at-tool-dispatch.md``.
"""

from __future__ import annotations

import time
import uuid

import pytest

from openjarvis.agents.approvals import (
    ApprovalError,
    ApprovalStore,
    args_hash,
    normalize_args,
)
from openjarvis.agents.manager import AgentManager
from openjarvis.core.config import ApprovalGatingConfig
from openjarvis.core.types import ToolCall
from openjarvis.server.managed_agent_runtime import ManagedAgentRuntime


def _insert_task(manager: AgentManager, agent_id: str, status: str = "pending") -> str:
    """Insert an ``agent_tasks`` row directly.

    ``AgentManager.create_task`` requires a resolvable project-task link;
    these tests only need a plain row to observe the status transition.
    """
    task_id = uuid.uuid4().hex[:12]
    manager._conn.execute(
        "INSERT INTO agent_tasks (id, agent_id, description, status, created_at)"
        " VALUES (?, ?, ?, ?, ?)",
        (task_id, agent_id, "test task", status, time.time()),
    )
    manager._conn.commit()
    return task_id


@pytest.fixture
def env(tmp_path):
    db = str(tmp_path / "agents.db")
    manager = AgentManager(db)
    store = ApprovalStore(db)  # colocated, production pattern
    agent = manager.create_agent(
        name="Gated",
        config={"requires_approval_tools": ["delete_files"]},
    )
    yield manager, store, agent
    store.close()
    closer = getattr(manager, "close", None)
    if callable(closer):
        closer()


def _runtime(manager, store, *, enabled: bool) -> ManagedAgentRuntime:
    return ManagedAgentRuntime(
        manager,
        None,
        approval_store=store,
        approval_gating=ApprovalGatingConfig(enabled=enabled),
    )


def _call(path: str = "/tmp/x", name: str = "delete_files") -> ToolCall:
    return ToolCall(id="1", name=name, arguments=f'{{"path": "{path}"}}')


# -- gate is a no-op unless fully armed --------------------------------


def test_gate_off_is_noop(env):
    manager, store, agent = env
    rt = _runtime(manager, store, enabled=False)
    assert rt._approval_gate(agent, _call()) is None
    assert store.list() == []


def test_tool_not_in_policy_is_noop(env):
    manager, store, agent = env
    rt = _runtime(manager, store, enabled=True)
    assert rt._approval_gate(agent, _call(name="calculator")) is None
    assert store.list() == []


def test_no_store_is_noop(env):
    manager, _store, agent = env
    rt = ManagedAgentRuntime(
        manager,
        None,
        approval_store=None,
        approval_gating=ApprovalGatingConfig(enabled=True),
    )
    assert rt._approval_gate(agent, _call()) is None


# -- first gated call with no prior decision blocks --------------------


def test_gated_tool_without_approval_blocks_and_creates_pending(env):
    manager, store, agent = env
    task_id = _insert_task(manager, agent["id"])
    rt = _runtime(manager, store, enabled=True)

    result = rt._approval_gate(agent, _call())

    assert result is not None
    assert result.success is False
    assert "approval" in result.content.lower()

    pending = store.list(state="pending")
    assert len(pending) == 1
    assert pending[0].capability == "delete_files"
    assert pending[0].task_id == task_id

    row = manager._conn.execute(
        "SELECT status, requires_approval FROM agent_tasks WHERE id = ?",
        (task_id,),
    ).fetchone()
    assert row["status"] == "awaiting_approval"
    assert row["requires_approval"] == 1


# -- granted: runs exactly once, then the grant is spent ---------------


def test_granted_approval_runs_once_then_consumed(env):
    manager, store, agent = env
    _insert_task(manager, agent["id"])
    rt = _runtime(manager, store, enabled=True)
    tc = _call()

    req = store.request(
        agent_id=agent["id"],
        capability="delete_files",
        args={"path": "/tmp/x"},
    )
    store.grant(req.id, resolved_by="human-admin")

    # First call: the grant authorizes it -> allowed.
    assert rt._approval_gate(agent, tc) is None
    assert store.get(req.id).consumed_at is not None

    # Second identical call: the grant is spent -> blocked anew.
    result = rt._approval_gate(agent, tc)
    assert result is not None
    assert result.success is False
    assert len(store.list(state="pending")) == 1


# -- denied: failed result, no execution -------------------------------


def test_denied_approval_returns_failed_result(env):
    manager, store, agent = env
    rt = _runtime(manager, store, enabled=True)

    req = store.request(
        agent_id=agent["id"],
        capability="delete_files",
        args={"path": "/tmp/x"},
    )
    store.deny(req.id, resolved_by="human-admin", reason="too risky")

    result = rt._approval_gate(agent, _call())
    assert result is not None
    assert result.success is False
    assert "denied" in result.content.lower()
    assert "too risky" in result.content


# -- a grant authorizes one specific argument set ----------------------


def test_args_hash_scopes_grant(env):
    manager, store, agent = env
    _insert_task(manager, agent["id"])
    rt = _runtime(manager, store, enabled=True)

    granted = store.request(
        agent_id=agent["id"],
        capability="delete_files",
        args={"path": "/tmp/safe"},
    )
    store.grant(granted.id, resolved_by="human-admin")

    # A different path -> different hash -> not authorized.
    blocked = rt._approval_gate(agent, _call(path="/etc"))
    assert blocked is not None
    assert blocked.success is False

    # The exact granted call is still allowed.
    assert rt._approval_gate(agent, _call(path="/tmp/safe")) is None


# -- self-approval hardening ------------------------------------------


def test_self_grant_rejected(env):
    _manager, store, agent = env
    req = store.request(
        agent_id=agent["id"], capability="delete_files", args={}
    )
    with pytest.raises(ApprovalError):
        store.grant(req.id, resolved_by=agent["id"])

    # The request is untouched and a human can still grant it.
    assert store.get(req.id).state == "pending"
    granted = store.grant(req.id, resolved_by="human-admin")
    assert granted.state == "granted"


# -- hash helpers ------------------------------------------------------


def test_args_hash_is_stable_across_key_order_and_whitespace():
    assert args_hash('{"b": 1, "a": 2}') == args_hash('{"a": 2, "b": 1}')
    assert normalize_args('  {"a": 1}  ') == normalize_args({"a": 1})
    assert args_hash("not json") == args_hash("not json")
    assert args_hash('{"a": 1}') != args_hash('{"a": 2}')
