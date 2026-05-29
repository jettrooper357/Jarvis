"""The streaming chat path imports a pasted outline deterministically.

Regression for the "No response was generated" failure: a large
Category/Task/SubTask paste sent through the Chief (streaming) used to be
handed to the model, which cannot echo the whole outline back as a
``project_import_outline`` argument within ``max_tokens`` -- it burned the
turn budget and streamed nothing. The runtime now short-circuits to a
server-side import before any model call.
"""

from __future__ import annotations

import pytest

from openjarvis.agents.manager import AgentManager
from openjarvis.projects.store import ProjectStore
from openjarvis.server.agent_manager_routes import _stream_managed_agent

_OUTLINE = """add this to the Veridex Project - Lowest level is a Category, \
Second level is a Task (Task:), the third level is a subtask (like SubTask:)
Category: Project Initiation and Planning

Task: Define Product Foundation

SubTask: Confirm final product name: Veridex
SubTask: Confirm MVP scope

Task: Define User Personas

SubTask: Create persona for debate user

Catgory: Testing and Quality Assurance

Task: Unit Testing

SubTask: Test claim services
SubTask: Test evidence services
"""


class _NoStreamEngine:
    """Duck-typed engine whose stream_full must never be reached."""

    engine_id = "fake"
    _model = "fake-model"

    def __init__(self) -> None:
        self.stream_full_called = False

    async def stream_full(self, *args, **kwargs):
        self.stream_full_called = True
        if False:  # pragma: no cover - make this an async generator
            yield None
        raise AssertionError("stream_full must not be called for a bulk outline")


@pytest.mark.asyncio
async def test_streaming_chat_imports_bulk_outline_without_model(tmp_path):
    project_store = ProjectStore(tmp_path / "projects.db")
    manager = AgentManager(
        db_path=str(tmp_path / "agents.db"),
        project_store=project_store,
    )
    try:
        chief = manager.create_agent(
            name="Chief Orchestrator",
            agent_type="simple",
            org_role="Chief Orchestrator",
            config={"max_turns": 3},
        )
        msg = manager.send_message(chief["id"], _OUTLINE, mode="immediate")
        engine = _NoStreamEngine()

        resp = await _stream_managed_agent(
            manager=manager,
            agent_record=manager.get_agent(chief["id"]),
            user_content=_OUTLINE,
            message_id=msg["id"],
            engine=engine,
            bus=None,
            app_state=None,
        )

        chunks = []
        async for chunk in resp.body_iterator:
            chunks.append(chunk if isinstance(chunk, str) else chunk.decode())
        body = "".join(chunks)

        # The model path was never taken.
        assert engine.stream_full_called is False
        # The summary streamed to the client, and the tool call surfaced.
        assert "Imported" in body
        assert "project_import_outline" in body
        assert "[DONE]" in body

        # The outline was materialized into the Veridex project.
        project = next(
            p for p in project_store.list_projects() if p["name"] == "Veridex"
        )
        tasks = project_store.list_tasks(project["id"])
        assert len([t for t in tasks if not t["parent_task_id"]]) == 3
        assert len([t for t in tasks if t["parent_task_id"]]) == 5

        # The BackgroundTask persists the chief's reply with the tool call.
        if resp.background is not None:
            resp.background.func()
        replies = [
            m
            for m in manager.list_messages(chief["id"])
            if m["direction"] == "agent_to_user"
        ]
        assert replies
        assert replies[0]["tool_calls"][0]["tool"] == "project_import_outline"
    finally:
        manager.close()
        project_store.close()
