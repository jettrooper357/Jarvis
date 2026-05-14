from __future__ import annotations

import tempfile
from pathlib import Path

from openjarvis.agents.manager import AgentManager
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
                                    '"status":"pending"}'
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
