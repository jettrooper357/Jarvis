"""HTTP route tests for chief-pending and chief-resume."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any, Dict, List

import pytest

from openjarvis.agents.manager import AgentManager


try:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    HAS_FASTAPI = True
except ImportError:
    HAS_FASTAPI = False


class _StubProjectStore:
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


_QUESTION_PAYLOAD = {
    "question": "When should the rollout go live?",
    "reason": "Need a date to schedule.",
    "expected_response_type": "free_text",
    "options": ["next week", "next month"],
}

_COMPLETE_RESPONSE = json.dumps(
    {
        "action": "complete",
        "reason": "User supplied date.",
        "final_report": {
            "status": "completed",
            "summary": "Rollout scheduled.",
        },
    }
)


def _checkpoint_chief(manager: AgentManager, agent_id: str) -> None:
    """Hand-roll the checkpoint a real chief pause would leave behind."""
    manager.save_checkpoint(
        agent_id,
        tick_id="test_run",
        conversation_state={
            "messages": [
                {"role": "user", "content": "Plan the rollout."},
            ],
        },
        tool_state={
            "tool_results": [],
            "already_delegated": False,
            "turns": 1,
            "question": _QUESTION_PAYLOAD,
            "trace_id": "trace_abc",
            "run_id": "run_xyz",
        },
    )
    manager.update_agent(agent_id, status="input_required")


@pytest.fixture
def manager(tmp_path: Path):
    mgr = AgentManager(
        db_path=str(tmp_path / "agents.db"),
        project_store=_StubProjectStore(),
    )
    yield mgr
    mgr.close()


@pytest.mark.skipif(not HAS_FASTAPI, reason="fastapi not installed")
class TestChiefPendingRoute:
    @pytest.fixture
    def client(self, manager):
        from openjarvis.server.agent_manager_routes import (
            create_agent_manager_router,
        )

        app = FastAPI()
        routers = create_agent_manager_router(manager)
        agents_router, *_ = routers
        app.include_router(agents_router)
        return TestClient(app)

    def test_chief_pending_not_found(self, client):
        resp = client.get("/v1/managed-agents/nonexistent/chief-pending")
        assert resp.status_code == 404

    def test_chief_pending_returns_false_for_idle_agent(self, client, manager):
        agent = manager.create_agent(name="Idle Chief", org_role="chief orchestrator")
        resp = client.get(f"/v1/managed-agents/{agent['id']}/chief-pending")
        assert resp.status_code == 200
        body = resp.json()
        assert body == {"pending": False}

    def test_chief_pending_returns_question_for_paused_agent(
        self, client, manager
    ):
        agent = manager.create_agent(
            name="Paused Chief", org_role="chief orchestrator"
        )
        _checkpoint_chief(manager, agent["id"])
        resp = client.get(f"/v1/managed-agents/{agent['id']}/chief-pending")
        assert resp.status_code == 200
        body = resp.json()
        assert body["pending"] is True
        assert body["question"]["question"] == _QUESTION_PAYLOAD["question"]
        assert body["question"]["options"] == _QUESTION_PAYLOAD["options"]
        assert body["run_id"] == "run_xyz"
        assert body["turns_so_far"] == 1


@pytest.mark.skipif(not HAS_FASTAPI, reason="fastapi not installed")
class TestChiefResumeRoute:
    @pytest.fixture
    def app_and_manager(self, manager):
        from openjarvis.server.agent_manager_routes import (
            create_agent_manager_router,
        )
        from tests.agents.fake_engine import FakeEngine

        engine = FakeEngine([{"content": _COMPLETE_RESPONSE}])

        app = FastAPI()
        # The route reads engine off app.state.engine.
        app.state.engine = engine
        app.state.model = "fake-model"
        app.state.trace_store = None
        routers = create_agent_manager_router(manager)
        agents_router, *_ = routers
        app.include_router(agents_router)
        return app, manager, engine

    def test_chief_resume_not_found(self, app_and_manager):
        app, _mgr, _engine = app_and_manager
        client = TestClient(app)
        resp = client.post(
            "/v1/managed-agents/nonexistent/chief-resume",
            json={"answer": "hi"},
        )
        assert resp.status_code == 404

    def test_chief_resume_rejects_idle_agent(self, app_and_manager):
        app, mgr, _engine = app_and_manager
        agent = mgr.create_agent(name="Idle", org_role="chief orchestrator")
        client = TestClient(app)
        resp = client.post(
            f"/v1/managed-agents/{agent['id']}/chief-resume",
            json={"answer": "hi"},
        )
        assert resp.status_code == 409
        assert "input" in resp.json()["detail"].lower()

    def test_chief_resume_requires_answer(self, app_and_manager):
        app, mgr, _engine = app_and_manager
        agent = mgr.create_agent(name="Paused", org_role="chief orchestrator")
        _checkpoint_chief(mgr, agent["id"])
        client = TestClient(app)
        resp = client.post(
            f"/v1/managed-agents/{agent['id']}/chief-resume",
            json={"answer": "   "},
        )
        assert resp.status_code == 400
        assert "answer" in resp.json()["detail"].lower()

    def test_chief_resume_happy_path(self, app_and_manager):
        app, mgr, engine = app_and_manager
        agent = mgr.create_agent(
            name="Paused Happy",
            org_role="chief orchestrator",
            config={
                "model": "fake-model",
                "orchestrator_mode": "chief",
                "max_turns": 3,
            },
        )
        _checkpoint_chief(mgr, agent["id"])

        client = TestClient(app)
        resp = client.post(
            f"/v1/managed-agents/{agent['id']}/chief-resume",
            json={"answer": "Launch on 2026-06-01."},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert "Rollout scheduled" in body["response"]
        assert body["status"] == "idle"
        # The engine should have been called exactly once for the resume.
        assert engine.call_count == 1

    def test_trace_tree_endpoint(self, app_and_manager):
        """The tree endpoint walks descendants via parent_trace_id."""
        from openjarvis.core.types import Trace
        from openjarvis.traces.store import TraceStore

        app, mgr, _engine = app_and_manager
        chief = mgr.create_agent(name="Tree Chief", org_role="chief orchestrator")
        worker_a = mgr.create_agent(
            name="Tree Worker A",
            org_role="researcher",
            manager_agent_id=chief["id"],
        )
        worker_b = mgr.create_agent(
            name="Tree Worker B",
            org_role="researcher",
            manager_agent_id=chief["id"],
        )

        # Replace the app's trace_store with a fresh in-memory one we can seed.
        store = TraceStore(":memory:")
        app.state.trace_store = store

        root = Trace(
            trace_id="root_trace",
            run_id="run_tree",
            agent=chief["id"],
            outcome="success",
            total_latency_seconds=1.5,
        )
        child_a = Trace(
            trace_id="child_a_trace",
            parent_trace_id="root_trace",
            run_id="run_tree",
            agent=worker_a["id"],
            outcome="success",
            total_latency_seconds=0.8,
        )
        child_b = Trace(
            trace_id="child_b_trace",
            parent_trace_id="root_trace",
            run_id="run_tree",
            agent=worker_b["id"],
            outcome="error",
            total_latency_seconds=0.3,
            result="boom",
        )
        store.save(root)
        store.save(child_a)
        store.save(child_b)

        client = TestClient(app)
        resp = client.get(
            f"/v1/managed-agents/{chief['id']}/traces/root_trace/tree"
        )
        assert resp.status_code == 200, resp.text
        tree = resp.json()["root"]
        assert tree["id"] == "root_trace"
        assert tree["parent_trace_id"] is None
        assert tree["run_id"] == "run_tree"
        assert len(tree["children"]) == 2

        child_ids = {c["id"] for c in tree["children"]}
        assert child_ids == {"child_a_trace", "child_b_trace"}
        for child in tree["children"]:
            assert child["parent_trace_id"] == "root_trace"
            assert child["run_id"] == "run_tree"
            assert child["children"] == []

        # 404 for unknown trace
        bad = client.get(
            f"/v1/managed-agents/{chief['id']}/traces/no-such-trace/tree"
        )
        assert bad.status_code == 404

        store.close()

    def test_chief_resume_accepts_auth_required(self, app_and_manager):
        """The resume route must work for credential pauses too."""
        app, mgr, _engine = app_and_manager
        agent = mgr.create_agent(
            name="Paused Auth",
            org_role="chief orchestrator",
            config={
                "model": "fake-model",
                "orchestrator_mode": "chief",
                "max_turns": 3,
            },
        )
        # Set up an auth_required checkpoint by hand.
        mgr.save_checkpoint(
            agent["id"],
            tick_id="test_run_auth",
            conversation_state={
                "messages": [{"role": "user", "content": "Call the gateway."}],
            },
            tool_state={
                "tool_results": [],
                "already_delegated": False,
                "turns": 1,
                "question": {
                    "question": "Paste your API token.",
                    "reason": "Cannot authenticate without it.",
                    "expected_response_type": "credential",
                },
                "trace_id": "trace_auth",
                "run_id": "run_auth",
            },
        )
        mgr.update_agent(agent["id"], status="auth_required")

        client = TestClient(app)
        pending = client.get(
            f"/v1/managed-agents/{agent['id']}/chief-pending"
        )
        assert pending.status_code == 200
        pending_body = pending.json()
        assert pending_body["pending"] is True
        assert pending_body["pause_kind"] == "auth_required"
        assert pending_body["question"]["expected_response_type"] == "credential"

        resp = client.post(
            f"/v1/managed-agents/{agent['id']}/chief-resume",
            json={"answer": "sk-fake-token-XYZ"},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "idle"
