from __future__ import annotations

import tempfile
from pathlib import Path

from openjarvis.agents.manager import AgentManager
from openjarvis.core.events import EventBus, EventType
from openjarvis.projects.store import ProjectStore
from openjarvis.server.managed_agent_runtime import ManagedAgentRuntime
from tests.agents.fake_engine import FakeEngine


def _tool_call(tool_id: str, tool_name: str, arguments: str) -> dict:
    return {
        "id": tool_id,
        "type": "function",
        "function": {
            "name": tool_name,
            "arguments": arguments,
        },
    }


def test_my_assistant_can_delegate_to_another_agent():
    with tempfile.TemporaryDirectory() as tmpdir:
        manager = AgentManager(db_path=str(Path(tmpdir) / "agents.db"))
        try:
            my_assistant = manager.create_agent(
                name="My Assistant",
                agent_type="deep_research",
                config={"max_turns": 6},
            )
            project_manager = manager.create_agent(
                name="Project Manager",
                agent_type="simple",
                config={"system_prompt": "You manage projects."},
            )

            engine = FakeEngine(
                [
                    {
                        "tool_calls": [
                            _tool_call(
                                "call-1",
                                "managed_agent_directory",
                                "{}",
                            )
                        ]
                    },
                    {
                        "tool_calls": [
                            _tool_call(
                                "call-2",
                                "managed_agent_delegate",
                                (
                                    '{"agent_name_or_id":"Project Manager",'
                                    '"message":"Build a short project plan."}'
                                ),
                            )
                        ]
                    },
                    {"content": "Project plan ready."},
                    {"content": "Project plan ready."},
                ]
            )

            runtime = ManagedAgentRuntime(manager, engine, default_model="fake-model")
            response = runtime.run(my_assistant["id"], "Help me plan this launch.")

            assert response == "Project plan ready."

            delegated_messages = manager.list_messages(project_manager["id"])
            assert any(
                msg["direction"] == "user_to_agent"
                and "Build a short project plan." in msg["content"]
                for msg in delegated_messages
            )
            assert any(
                msg["direction"] == "agent_to_user"
                and "Project plan ready." in msg["content"]
                for msg in delegated_messages
            )

            assistant_messages = manager.list_messages(my_assistant["id"])
            latest_assistant_reply = next(
                msg for msg in assistant_messages if msg["direction"] == "agent_to_user"
            )
            assert latest_assistant_reply["tool_calls"] is not None
            assert [entry["tool"] for entry in latest_assistant_reply["tool_calls"]] == [
                "managed_agent_directory",
                "managed_agent_delegate",
            ]
        finally:
            manager.close()


def test_agents_can_assign_tasks_and_message_each_other():
    with tempfile.TemporaryDirectory() as tmpdir:
        manager = AgentManager(db_path=str(Path(tmpdir) / "agents.db"))
        try:
            ceo = manager.create_agent(
                name="My Assistant",
                agent_type="deep_research",
                org_role="Chief Executive Officer (CEO)",
                config={"max_turns": 8},
            )
            developer = manager.create_agent(
                name="Developer",
                agent_type="simple",
                org_role="Developer",
                manager_agent_id=ceo["id"],
                config={"system_prompt": "You implement assigned work."},
            )

            engine = FakeEngine(
                [
                    {
                        "tool_calls": [
                            _tool_call(
                                "call-1",
                                "managed_agent_assign_task",
                                (
                                    '{"agent_name_or_id":"Developer",'
                                    '"description":"Implement the export endpoint.",'
                                    '"status":"pending","start_now":false}'
                                ),
                            )
                        ]
                    },
                    {
                        "tool_calls": [
                            _tool_call(
                                "call-2",
                                "managed_agent_message",
                                (
                                    '{"agent_name_or_id":"Developer",'
                                    '"message":"Start the export endpoint now and report back."}'
                                ),
                            )
                        ]
                    },
                    {"content": "I have started the export endpoint work."},
                    {"content": "Task assigned and developer confirmed."},
                ]
            )

            runtime = ManagedAgentRuntime(manager, engine, default_model="fake-model")
            response = runtime.run(ceo["id"], "Ship the export endpoint.")

            assert response == "Task assigned and developer confirmed."

            developer_tasks = manager.list_tasks(developer["id"])
            assert len(developer_tasks) == 1
            assert developer_tasks[0]["description"] == "Implement the export endpoint."
            assert developer_tasks[0]["assigned_by_agent_id"] == ceo["id"]

            developer_messages = manager.list_messages(developer["id"])
            assert any(
                msg["direction"] == "user_to_agent"
                and "Start the export endpoint now and report back." in msg["content"]
                for msg in developer_messages
            )
            assert any(
                msg["direction"] == "agent_to_user"
                and "I have started the export endpoint work." in msg["content"]
                for msg in developer_messages
            )

            ceo_messages = manager.list_messages(ceo["id"])
            ceo_reply = next(
                msg for msg in ceo_messages if msg["direction"] == "agent_to_user"
            )
            assert [entry["tool"] for entry in ceo_reply["tool_calls"]] == [
                "managed_agent_assign_task",
                "managed_agent_message",
            ]
        finally:
            manager.close()


def test_successful_project_create_completes_linked_agent_task(tmp_path, monkeypatch):
    project_store = ProjectStore(tmp_path / "projects.db")
    manager = AgentManager(
        db_path=str(tmp_path / "agents.db"),
        project_store=project_store,
    )
    monkeypatch.setattr(
        "openjarvis.tools.project_tools._project_store",
        lambda: project_store,
    )
    try:
        project_manager = manager.create_agent(
            name="Workflow Manager",
            agent_type="monitor_operative",
            org_role="Workflow Manager",
            config={"max_turns": 4},
        )
        tracker_project = project_store.create_project(
            name="Unassigned Work",
            status="Active",
        )
        tracker_task = project_store.create_task(
            tracker_project["id"],
            title="Start a new project called test project",
        )
        agent_task = manager.create_task(
            project_manager["id"],
            description="Start a new project called test project",
            status="active",
            project_task_id=tracker_task["id"],
        )

        engine = FakeEngine(
            [
                {
                    "tool_calls": [
                        _tool_call(
                            "call-1",
                            "project_create",
                            '{"name":"test project","status":"Active"}',
                        )
                    ]
                },
                {"content": "Created test project."},
            ]
        )

        runtime = ManagedAgentRuntime(
            manager,
            engine,
            default_model="fake-model",
        )
        response = runtime.run(
            project_manager["id"],
            "Start a new project called test project",
        )

        assert response == "Created test project."
        updated = manager._get_task(agent_task["id"])
        assert updated["status"] == "completed"
        assert "project setup tool" in updated["progress"]["note"]
    finally:
        manager.close()
        project_store.close()


def test_assign_task_starts_assignee_immediately_by_default():
    with tempfile.TemporaryDirectory() as tmpdir:
        manager = AgentManager(db_path=str(Path(tmpdir) / "agents.db"))
        try:
            ceo = manager.create_agent(
                name="My Assistant",
                agent_type="deep_research",
                org_role="Chief Executive Officer (CEO)",
                config={"max_turns": 6},
            )
            project_manager = manager.create_agent(
                name="Project Manager",
                agent_type="simple",
                org_role="Project Manager",
                manager_agent_id=ceo["id"],
                config={"system_prompt": "You manage assigned projects."},
            )

            engine = FakeEngine(
                [
                    {
                        "tool_calls": [
                            _tool_call(
                                "call-1",
                                "managed_agent_assign_task",
                                (
                                    '{"agent_name_or_id":"Project Manager",'
                                    '"description":"Set up a new test project.",'
                                    '"status":"active"}'
                                ),
                            )
                        ]
                    },
                    {"content": "I have started the new project and will post a plan next."},
                    {"content": "The project manager has started the project."},
                ]
            )

            runtime = ManagedAgentRuntime(manager, engine, default_model="fake-model")
            response = runtime.run(ceo["id"], "Start a new project.")

            assert response == "The project manager has started the project."

            project_tasks = manager.list_tasks(project_manager["id"])
            assert len(project_tasks) == 1
            assert project_tasks[0]["description"] == "Set up a new test project."
            assert project_tasks[0]["assigned_by_agent_id"] == ceo["id"]

            project_messages = manager.list_messages(project_manager["id"])
            assert any(
                msg["direction"] == "user_to_agent"
                and "You have been assigned a persistent task by My Assistant." in msg["content"]
                and "Set up a new test project." in msg["content"]
                for msg in project_messages
            )
            assert any(
                msg["direction"] == "agent_to_user"
                and "started the new project" in msg["content"]
                for msg in project_messages
            )

            ceo_messages = manager.list_messages(ceo["id"])
            ceo_reply = next(
                msg for msg in ceo_messages if msg["direction"] == "agent_to_user"
            )
            assert ceo_reply["tool_calls"] is not None
            assert ceo_reply["tool_calls"][0]["tool"] == "managed_agent_assign_task"
            assert "Initial response from Project Manager" in ceo_reply["tool_calls"][0]["result"]
        finally:
            manager.close()


def test_ceo_can_inspect_subordinate_state():
    with tempfile.TemporaryDirectory() as tmpdir:
        manager = AgentManager(db_path=str(Path(tmpdir) / "agents.db"))
        try:
            ceo = manager.create_agent(
                name="My Assistant",
                agent_type="monitor_operative",
                org_role="Chief Executive Officer (CEO)",
                config={"system_prompt": "Lead the organization."},
            )
            worker = manager.create_agent(
                name="Developer",
                agent_type="monitor_operative",
                org_role="Developer",
                manager_agent_id=ceo["id"],
                config={"system_prompt": "Build things."},
            )
            manager.create_task(
                worker["id"],
                description="Ship the export endpoint.",
                status="active",
                assigned_by_agent_id=ceo["id"],
            )
            manager.send_message(worker["id"], "Please status this work.", mode="delegated")
            manager.store_agent_response(worker["id"], "The export endpoint is underway.")
            manager.add_learning_log(
                worker["id"],
                "tool_call",
                "Ran apply_patch",
                {"tool": "apply_patch"},
            )

            engine = FakeEngine(
                [
                    {
                        "tool_calls": [
                            _tool_call(
                                "call-1",
                                "managed_agent_inspect",
                                '{"agent_name_or_id":"Developer"}',
                            )
                        ]
                    },
                    {"content": "Inspection complete."},
                ]
            )

            runtime = ManagedAgentRuntime(manager, engine, default_model="fake-model")
            response = runtime.run(ceo["id"], "Inspect the developer.")

            assert response == "Inspection complete."
            ceo_messages = manager.list_messages(ceo["id"])
            ceo_reply = next(
                msg for msg in ceo_messages if msg["direction"] == "agent_to_user"
            )
            assert ceo_reply["tool_calls"] is not None
            assert ceo_reply["tool_calls"][0]["tool"] == "managed_agent_inspect"
            inspect_result = ceo_reply["tool_calls"][0]["result"]
            assert "Ship the export endpoint." in inspect_result
            assert "The export endpoint is underway." in inspect_result
            assert "Ran apply_patch" in inspect_result
        finally:
            manager.close()


def test_subordinate_cannot_inspect_manager_state():
    with tempfile.TemporaryDirectory() as tmpdir:
        manager = AgentManager(db_path=str(Path(tmpdir) / "agents.db"))
        try:
            ceo = manager.create_agent(
                name="My Assistant",
                agent_type="monitor_operative",
                org_role="Chief Executive Officer (CEO)",
                config={"system_prompt": "Lead the organization."},
            )
            developer = manager.create_agent(
                name="Developer",
                agent_type="monitor_operative",
                org_role="Developer",
                manager_agent_id=ceo["id"],
                config={"system_prompt": "Build things."},
            )

            engine = FakeEngine(
                [
                    {
                        "tool_calls": [
                            _tool_call(
                                "call-1",
                                "managed_agent_inspect",
                                '{"agent_name_or_id":"My Assistant"}',
                            )
                        ]
                    },
                    {"content": "Inspection denied."},
                ]
            )

            runtime = ManagedAgentRuntime(manager, engine, default_model="fake-model")
            response = runtime.run(developer["id"], "Inspect the CEO.")

            assert response == "Inspection denied."
            developer_messages = manager.list_messages(developer["id"])
            developer_reply = next(
                msg for msg in developer_messages if msg["direction"] == "agent_to_user"
            )
            assert developer_reply["tool_calls"] is not None
            assert developer_reply["tool_calls"][0]["tool"] == "managed_agent_inspect"
            assert "Access denied" in developer_reply["tool_calls"][0]["result"]
        finally:
            manager.close()


def test_runtime_publishes_agent_events_for_external_turns():
    with tempfile.TemporaryDirectory() as tmpdir:
        manager = AgentManager(db_path=str(Path(tmpdir) / "agents.db"))
        try:
            agent = manager.create_agent(
                name="Project Manager",
                agent_type="monitor_operative",
                config={"system_prompt": "You manage projects."},
            )
            bus = EventBus(record_history=True)
            engine = FakeEngine([{"content": "Project acknowledged."}])

            runtime = ManagedAgentRuntime(
                manager,
                engine,
                bus=bus,
                default_model="fake-model",
            )
            response = runtime.run(agent["id"], "Start the project.")

            assert response == "Project acknowledged."
            event_types = [event.event_type for event in bus.history]
            assert EventType.AGENT_TICK_START in event_types
            assert EventType.AGENT_MESSAGE_RECEIVED in event_types
            assert EventType.AGENT_TICK_END in event_types
            relevant = [
                event for event in bus.history
                if event.event_type in {
                    EventType.AGENT_TICK_START,
                    EventType.AGENT_MESSAGE_RECEIVED,
                    EventType.AGENT_TICK_END,
                }
            ]
            assert all(event.data.get("agent_id") == agent["id"] for event in relevant)
        finally:
            manager.close()
