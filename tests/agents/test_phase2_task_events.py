"""Phase 2C — task.* events emit when an EventBus is wired.

Verifies the additive contract: pass no bus → behavior unchanged
(default for tests / CLI); pass a bus → ``task.created`` /
``task.updated`` / ``task.completed`` / ``task.failed`` /
``task.delegated`` fire with the documented payload shape.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from openjarvis.agents.manager import AgentManager
from openjarvis.core.events import EventBus, EventType


class _FakeProjectStore:
    """Minimal project store stub satisfying AgentManager's linkage."""

    def __init__(self) -> None:
        self._tasks: Dict[str, Dict[str, Any]] = {}
        self._projects: Dict[str, Dict[str, Any]] = {
            "proj-default": {"id": "proj-default", "name": "Tests"},
        }

    def get_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        return self._tasks.get(task_id)

    def get_project(self, project_id: str) -> Optional[Dict[str, Any]]:
        return self._projects.get(project_id)

    def list_projects(self) -> List[Dict[str, Any]]:
        return list(self._projects.values())

    def list_tasks_for_project(self, project_id: str) -> List[Dict[str, Any]]:
        return [t for t in self._tasks.values() if t.get("project_id") == project_id]

    def create_task(self, *args: Any, **kwargs: Any) -> Dict[str, Any]:
        # AgentManager calls this with either project_id as first positional
        # or as a kwarg; normalize both.
        project_id = args[0] if args else kwargs.get("project_id", "proj-default")
        task = {
            "id": kwargs.get("id") or f"pt-{len(self._tasks) + 1}",
            "title": kwargs.get("title", "task"),
            "project_id": project_id,
            "parent_task_id": kwargs.get("parent_task_id"),
            "status": kwargs.get("status", "Open"),
            "start_date": kwargs.get("start_date"),
        }
        self._tasks[task["id"]] = task
        return task


def _seed_project_task(store: _FakeProjectStore, task_id: str = "pt-1") -> Dict[str, Any]:
    return store.create_task(id=task_id, title="Bench", project_id="proj-default")


def _new_manager(tmp_path, *, bus: Optional[EventBus] = None) -> AgentManager:
    store = _FakeProjectStore()
    _seed_project_task(store)
    return AgentManager(
        db_path=str(tmp_path / "agents.db"),
        project_store=store,
        event_bus=bus,
    )


def test_no_bus_means_no_events_no_crash(tmp_path) -> None:
    mgr = _new_manager(tmp_path)  # bus=None
    agent = mgr.create_agent("solo")
    task = mgr.create_task(
        agent["id"],
        description="solo work",
        status="active",
        project_task_id="pt-1",
    )
    mgr.update_task(task["id"], status="completed")
    # No crash; no observable difference.
    assert task["status"] == "active"
    mgr.close()


def test_task_created_event_fires_with_bus(tmp_path) -> None:
    bus = EventBus(record_history=True)
    mgr = _new_manager(tmp_path, bus=bus)
    agent = mgr.create_agent("emitter")
    mgr.create_task(
        agent["id"],
        description="hello",
        status="pending",
        project_task_id="pt-1",
    )
    types = [e.event_type for e in bus.history]
    assert EventType.TASK_CREATED in types
    created = next(e for e in bus.history if e.event_type == EventType.TASK_CREATED)
    assert created.data["agent_id"] == agent["id"]
    assert created.data["description"] == "hello"
    assert created.data["status"] == "pending"
    mgr.close()


def test_task_delegated_event_fires_when_assigned_by_set(tmp_path) -> None:
    bus = EventBus(record_history=True)
    mgr = _new_manager(tmp_path, bus=bus)
    boss = mgr.create_agent("boss")
    worker = mgr.create_agent("worker")
    mgr.create_task(
        worker["id"],
        description="do the thing",
        status="active",
        assigned_by_agent_id=boss["id"],
        project_task_id="pt-1",
    )
    types = [e.event_type for e in bus.history]
    assert EventType.TASK_DELEGATED in types
    delegated = next(e for e in bus.history if e.event_type == EventType.TASK_DELEGATED)
    assert delegated.data["from_agent_id"] == boss["id"]
    assert delegated.data["to_agent_id"] == worker["id"]
    mgr.close()


def test_task_completed_and_failed_events_fire_on_terminal_transition(tmp_path) -> None:
    bus = EventBus(record_history=True)
    mgr = _new_manager(tmp_path, bus=bus)
    agent = mgr.create_agent("transitioner")
    task = mgr.create_task(
        agent["id"],
        description="work",
        status="active",
        project_task_id="pt-1",
    )
    bus._history.clear()  # type: ignore[attr-defined]
    mgr.update_task(task["id"], status="completed")
    types_after = [e.event_type for e in bus.history]
    assert EventType.TASK_UPDATED in types_after
    assert EventType.TASK_COMPLETED in types_after
    assert EventType.TASK_FAILED not in types_after

    other = mgr.create_task(
        agent["id"],
        description="other",
        status="active",
        project_task_id="pt-1",
    )
    bus._history.clear()  # type: ignore[attr-defined]
    mgr.update_task(other["id"], status="failed")
    types_after_fail = [e.event_type for e in bus.history]
    assert EventType.TASK_FAILED in types_after_fail
    assert EventType.TASK_COMPLETED not in types_after_fail
    mgr.close()


def test_task_updated_event_fires_for_non_terminal_change(tmp_path) -> None:
    bus = EventBus(record_history=True)
    mgr = _new_manager(tmp_path, bus=bus)
    agent = mgr.create_agent("desc-changer")
    task = mgr.create_task(
        agent["id"],
        description="initial",
        status="active",
        project_task_id="pt-1",
    )
    bus._history.clear()  # type: ignore[attr-defined]
    mgr.update_task(task["id"], description="revised")
    types_after = [e.event_type for e in bus.history]
    assert EventType.TASK_UPDATED in types_after
    assert EventType.TASK_COMPLETED not in types_after
    assert EventType.TASK_FAILED not in types_after
    mgr.close()


def test_publish_failure_does_not_break_task_lifecycle(tmp_path) -> None:
    """A subscriber that raises must not propagate into the task path."""
    bus = EventBus()
    def _angry(_event: Any) -> None:
        raise RuntimeError("boom")
    bus.subscribe(EventType.TASK_CREATED, _angry)
    mgr = _new_manager(tmp_path, bus=bus)
    agent = mgr.create_agent("calm")
    # If this raises, the lifecycle is broken — must succeed.
    task = mgr.create_task(
        agent["id"],
        description="should still work",
        status="pending",
        project_task_id="pt-1",
    )
    assert task["id"]
    mgr.close()
