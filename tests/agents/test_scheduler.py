"""Tests for AgentScheduler tick scheduling."""

from __future__ import annotations

import tempfile
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest


@pytest.fixture
def manager():
    from openjarvis.agents.manager import AgentManager

    with tempfile.TemporaryDirectory() as tmpdir:
        mgr = AgentManager(db_path=str(Path(tmpdir) / "agents.db"))
        yield mgr
        mgr.close()


class TestSchedulerBasic:
    def test_create_scheduler(self, manager):
        from openjarvis.agents.scheduler import AgentScheduler

        executor = MagicMock()
        scheduler = AgentScheduler(manager=manager, executor=executor)
        assert scheduler is not None

    def test_register_agent_with_interval(self, manager):
        from openjarvis.agents.scheduler import AgentScheduler

        executor = MagicMock()
        scheduler = AgentScheduler(manager=manager, executor=executor)

        agent = manager.create_agent(
            name="test",
            agent_type="monitor_operative",
            config={"schedule_type": "interval", "schedule_value": 60},
        )
        scheduler.register_agent(agent["id"])
        assert agent["id"] in scheduler.registered_agents

    def test_register_agent_with_cron(self, manager):
        from openjarvis.agents.scheduler import AgentScheduler

        executor = MagicMock()
        scheduler = AgentScheduler(manager=manager, executor=executor)

        agent = manager.create_agent(
            name="test",
            agent_type="monitor_operative",
            config={"schedule_type": "cron", "schedule_value": "0 9 * * *"},
        )
        scheduler.register_agent(agent["id"])
        assert agent["id"] in scheduler.registered_agents

    def test_deregister_agent(self, manager):
        from openjarvis.agents.scheduler import AgentScheduler

        executor = MagicMock()
        scheduler = AgentScheduler(manager=manager, executor=executor)

        agent = manager.create_agent(
            name="test",
            agent_type="monitor_operative",
            config={"schedule_type": "interval", "schedule_value": 60},
        )
        scheduler.register_agent(agent["id"])
        scheduler.deregister_agent(agent["id"])
        assert agent["id"] not in scheduler.registered_agents

    def test_manual_schedule_not_auto_registered(self, manager):
        from openjarvis.agents.scheduler import AgentScheduler

        executor = MagicMock()
        scheduler = AgentScheduler(manager=manager, executor=executor)

        agent = manager.create_agent(
            name="test",
            agent_type="monitor_operative",
            config={"schedule_type": "manual"},
        )
        scheduler.register_agent(agent["id"])
        # Manual agents are registered but never auto-fired
        assert agent["id"] in scheduler.registered_agents

    def test_start_stop(self, manager):
        from openjarvis.agents.scheduler import AgentScheduler

        executor = MagicMock()
        scheduler = AgentScheduler(manager=manager, executor=executor)
        scheduler.start()
        assert scheduler.is_running
        scheduler.stop()
        assert not scheduler.is_running

    def test_tick_fires_executor(self, manager):
        from openjarvis.agents.scheduler import AgentScheduler

        executor = MagicMock()
        scheduler = AgentScheduler(
            manager=manager, executor=executor, tick_interval=0.1
        )

        agent = manager.create_agent(
            name="test",
            agent_type="monitor_operative",
            config={"schedule_type": "interval", "schedule_value": 0},
        )
        scheduler.register_agent(agent["id"])
        scheduler.start()
        time.sleep(0.5)
        scheduler.stop()

        assert executor.execute_tick.call_count >= 1
        executor.execute_tick.assert_called_with(agent["id"])

    def test_skips_paused_agents(self, manager):
        from openjarvis.agents.scheduler import AgentScheduler

        executor = MagicMock()
        scheduler = AgentScheduler(
            manager=manager, executor=executor, tick_interval=0.1
        )

        agent = manager.create_agent(
            name="test",
            agent_type="monitor_operative",
            config={"schedule_type": "interval", "schedule_value": 0},
        )
        manager.pause_agent(agent["id"])
        scheduler.register_agent(agent["id"])
        scheduler.start()
        time.sleep(0.3)
        scheduler.stop()

        executor.execute_tick.assert_not_called()

    def test_backlog_fires_manual_agent_with_due_task(self, tmp_path):
        from openjarvis.agents.manager import AgentManager
        from openjarvis.agents.scheduler import AgentScheduler
        from openjarvis.projects.store import ProjectStore

        project_store = ProjectStore(tmp_path / "projects.db")
        mgr = AgentManager(str(tmp_path / "agents.db"), project_store=project_store)
        try:
            project = project_store.create_project(name="P", status="Active")
            project_task = project_store.create_task(project["id"], title="Build")
            agent = mgr.create_agent(
                name="worker",
                agent_type="monitor_operative",
                config={"schedule_type": "manual"},
            )
            mgr.create_task(
                agent["id"],
                description="Do the work",
                project_task_id=project_task["id"],
            )
            executor = MagicMock()
            scheduler = AgentScheduler(
                manager=mgr,
                executor=executor,
                task_poll_interval=0,
            )

            scheduler._check_task_backlog()

            executor.execute_tick.assert_called_once_with(agent["id"])
        finally:
            mgr.close()
            project_store.close()

    def test_backlog_skips_future_scheduled_task(self, tmp_path):
        from datetime import datetime, timedelta

        from openjarvis.agents.manager import AgentManager
        from openjarvis.agents.scheduler import AgentScheduler
        from openjarvis.projects.store import ProjectStore

        project_store = ProjectStore(tmp_path / "projects.db")
        mgr = AgentManager(str(tmp_path / "agents.db"), project_store=project_store)
        try:
            future = (datetime.now() + timedelta(days=1)).isoformat(
                timespec="minutes"
            )
            project = project_store.create_project(name="P", status="Active")
            project_task = project_store.create_task(
                project["id"],
                title="Later",
                start_date=future,
            )
            agent = mgr.create_agent(name="worker", agent_type="monitor_operative")
            mgr.create_task(
                agent["id"],
                description="Wait for schedule",
                project_task_id=project_task["id"],
            )
            executor = MagicMock()
            scheduler = AgentScheduler(
                manager=mgr,
                executor=executor,
                task_poll_interval=0,
            )

            scheduler._check_task_backlog()

            executor.execute_tick.assert_not_called()
        finally:
            mgr.close()
            project_store.close()
