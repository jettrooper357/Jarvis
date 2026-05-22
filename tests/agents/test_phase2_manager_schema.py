"""Phase 2A — agent_tasks additive columns + agent_config_versions tests.

Tests use raw INSERT against ``mgr._conn`` for ``agent_tasks`` rows so we
don't have to set up a full project store to satisfy
``create_task``'s project-task linkage requirement. The point of these
tests is the schema/migration shape, not the linkage helper.
"""

from __future__ import annotations

import json
import time
import uuid

from openjarvis.agents.manager import AgentManager


def _insert_raw_task(mgr: AgentManager, agent_id: str, **fields: object) -> str:
    """Insert a row directly to exercise the new columns end-to-end."""
    task_id = uuid.uuid4().hex[:12]
    columns = ["id", "agent_id", "description", "status", "created_at"]
    values = [
        task_id,
        agent_id,
        fields.pop("description", "raw task"),
        fields.pop("status", "pending"),
        fields.pop("created_at", time.time()),
    ]
    for col, val in fields.items():
        columns.append(col)
        values.append(val)
    placeholders = ", ".join(["?"] * len(columns))
    mgr._conn.execute(
        f"INSERT INTO agent_tasks ({', '.join(columns)}) VALUES ({placeholders})",
        values,
    )
    mgr._conn.commit()
    return task_id


def test_legacy_task_rows_are_readable_after_migration(tmp_path) -> None:
    """A row inserted with only the original columns still parses."""
    mgr = AgentManager(str(tmp_path / "agents.db"))
    agent = mgr.create_agent("legacy-agent")
    task_id = _insert_raw_task(mgr, agent["id"], description="legacy row")
    task = mgr._get_task(task_id)
    assert task is not None
    # New columns default to None / [] / False — never crash.
    assert task["parent_task_id"] is None
    assert task["root_task_id"] is None
    assert task["request_source"] is None
    assert task["requesting_user"] is None
    assert task["priority"] is None
    assert task["updated_at"] is None
    assert task["completed_at"] is None
    assert task["summary"] is None
    assert task["errors"] == []
    assert task["requires_user_input"] is False
    assert task["requires_approval"] is False
    assert task["task_session_id"] is None
    mgr.close()


def test_new_task_columns_round_trip(tmp_path) -> None:
    mgr = AgentManager(str(tmp_path / "agents.db"))
    agent = mgr.create_agent("ledger-agent")
    task_id = _insert_raw_task(
        mgr,
        agent["id"],
        description="rich row",
        parent_task_id="parent-x",
        root_task_id="root-y",
        request_source="chat",
        requesting_user="user-1",
        priority=3,
        updated_at=time.time(),
        completed_at=None,
        summary="initial summary",
        errors_json=json.dumps([{"code": "X", "message": "boom"}]),
        requires_user_input=1,
        requires_approval=1,
        task_session_id="sess-42",
    )
    task = mgr._get_task(task_id)
    assert task is not None
    assert task["parent_task_id"] == "parent-x"
    assert task["root_task_id"] == "root-y"
    assert task["request_source"] == "chat"
    assert task["requesting_user"] == "user-1"
    assert task["priority"] == 3
    assert task["summary"] == "initial summary"
    assert task["errors"] == [{"code": "X", "message": "boom"}]
    assert task["requires_user_input"] is True
    assert task["requires_approval"] is True
    assert task["task_session_id"] == "sess-42"
    mgr.close()


def test_config_version_written_on_update(tmp_path) -> None:
    mgr = AgentManager(str(tmp_path / "agents.db"))
    agent = mgr.create_agent(
        "evolver", config={"model": "qwen3:8b", "skills": ["search"]}
    )
    assert mgr.list_agent_config_versions(agent["id"]) == []

    mgr.update_agent(
        agent["id"],
        config={"model": "qwen3:8b", "skills": ["search", "code"]},
        updated_by="alice",
        change_summary="add code skill",
    )
    versions = mgr.list_agent_config_versions(agent["id"])
    assert len(versions) == 1
    v1 = versions[0]
    assert v1["version_number"] == 1
    assert v1["created_by"] == "alice"
    assert v1["summary"] == "add code skill"
    assert v1["snapshot"] == {
        "model": "qwen3:8b",
        "skills": ["search", "code"],
    }
    assert v1["diff"]["changed"]["skills"]["to"] == ["search", "code"]
    mgr.close()


def test_noop_config_update_does_not_append_version(tmp_path) -> None:
    mgr = AgentManager(str(tmp_path / "agents.db"))
    agent = mgr.create_agent("steady", config={"a": 1})
    mgr.update_agent(agent["id"], config={"a": 1})
    assert mgr.list_agent_config_versions(agent["id"]) == []
    mgr.close()


def test_revert_is_non_destructive(tmp_path) -> None:
    mgr = AgentManager(str(tmp_path / "agents.db"))
    agent = mgr.create_agent("rewinder", config={"v": 1})
    mgr.update_agent(agent["id"], config={"v": 2})
    mgr.update_agent(agent["id"], config={"v": 3})

    versions = mgr.list_agent_config_versions(agent["id"])
    assert [v["version_number"] for v in versions] == [2, 1]
    v1 = next(v for v in versions if v["version_number"] == 1)

    reverted = mgr.revert_agent_config_to_version(
        agent["id"], v1["id"], updated_by="bob"
    )
    assert reverted["config"] == {"v": 2}  # snapshot of v1 was {"v": 2}

    versions_after = mgr.list_agent_config_versions(agent["id"])
    # History is append-only: prior versions retained, revert is a new row.
    assert [v["version_number"] for v in versions_after] == [3, 2, 1]
    assert versions_after[0]["summary"].startswith("Revert to version")
    assert versions_after[0]["created_by"] == "bob"
    mgr.close()


def test_revert_unknown_version_raises(tmp_path) -> None:
    mgr = AgentManager(str(tmp_path / "agents.db"))
    agent = mgr.create_agent("hopeful", config={"v": 1})
    try:
        mgr.revert_agent_config_to_version(agent["id"], "deadbeef")
    except ValueError as exc:
        assert "not found" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected ValueError")
    mgr.close()
