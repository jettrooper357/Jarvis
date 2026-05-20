"""Tests for model pull / delete API endpoints and streaming resilience."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from openjarvis.server.app import create_app  # noqa: E402

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_engine(engine_id="mock", models=None):
    engine = MagicMock()
    engine.engine_id = engine_id
    engine.health.return_value = True
    engine.list_models.return_value = models or ["test-model"]
    engine.generate.return_value = {
        "content": "Hello",
        "usage": {"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8},
        "model": "test-model",
        "finish_reason": "stop",
    }

    async def mock_stream(messages, *, model, temperature=0.7, max_tokens=1024, **kw):
        for token in ["Hello", " ", "world"]:
            yield token

    engine.stream = mock_stream
    return engine


def _make_ollama_engine(models=None):
    """Create a mock engine that looks like OllamaEngine."""
    engine = _make_engine(engine_id="ollama", models=models)
    engine._host = "http://localhost:11434"
    return engine


def _app(engine, engine_name="mock"):
    return create_app(engine, "test-model", engine_name=engine_name)


# ---------------------------------------------------------------------------
# Model pull endpoint
# ---------------------------------------------------------------------------


class TestModelPull:
    def test_pull_requires_model_field(self):
        engine = _make_ollama_engine()
        client = TestClient(_app(engine, engine_name="ollama"))
        resp = client.post("/v1/models/pull", json={})
        assert resp.status_code == 400
        assert "model" in resp.json()["detail"].lower()

    def test_pull_rejects_non_ollama_engine(self):
        engine = _make_engine(engine_id="vllm")
        client = TestClient(_app(engine, engine_name="vllm"))
        resp = client.post("/v1/models/pull", json={"model": "foo"})
        assert resp.status_code == 501

    def test_pull_success(self):
        engine = _make_ollama_engine()
        client = TestClient(_app(engine, engine_name="ollama"))

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.raise_for_status = MagicMock()

        with patch("httpx.Client") as MockClient:
            instance = MockClient.return_value
            instance.post.return_value = mock_resp
            instance.close = MagicMock()

            resp = client.post("/v1/models/pull", json={"model": "qwen3.5:4b"})

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["model"] == "qwen3.5:4b"

    def test_pull_ollama_unreachable(self):
        engine = _make_ollama_engine()
        client = TestClient(_app(engine, engine_name="ollama"))

        import httpx

        with patch("httpx.Client") as MockClient:
            instance = MockClient.return_value
            instance.post.side_effect = httpx.ConnectError("refused")
            instance.close = MagicMock()

            resp = client.post("/v1/models/pull", json={"model": "foo"})

        assert resp.status_code == 502


# ---------------------------------------------------------------------------
# Model delete endpoint
# ---------------------------------------------------------------------------


class TestModelDelete:
    def test_delete_rejects_non_ollama(self):
        engine = _make_engine(engine_id="vllm")
        client = TestClient(_app(engine, engine_name="vllm"))
        resp = client.delete("/v1/models/test-model")
        assert resp.status_code == 501

    def test_delete_success(self):
        engine = _make_ollama_engine()
        client = TestClient(_app(engine, engine_name="ollama"))

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.raise_for_status = MagicMock()

        with patch("httpx.Client") as MockClient:
            instance = MockClient.return_value
            instance.request.return_value = mock_resp
            instance.close = MagicMock()

            resp = client.delete("/v1/models/qwen3:0.6b")

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "deleted"
        assert data["model"] == "qwen3:0.6b"


# ---------------------------------------------------------------------------
# Streaming resilience
# ---------------------------------------------------------------------------


class TestStreamingResilience:
    """Verify streaming handles errors gracefully."""

    def test_stream_error_returns_error_chunk(self):
        """When the engine raises during streaming, error is sent as content."""
        engine = _make_engine()

        async def failing_stream(messages, *, model, **kw):
            yield "partial"
            raise RuntimeError("model not found")

        engine.stream = failing_stream
        app = create_app(engine, "test-model")
        client = TestClient(app)

        resp = client.post(
            "/v1/chat/completions",
            json={
                "model": "bad-model",
                "messages": [{"role": "user", "content": "Hello"}],
                "stream": True,
            },
        )
        assert resp.status_code == 200

        # Should contain partial content + error message + [DONE]
        text = resp.text
        assert "partial" in text
        assert "model not found" in text
        assert "[DONE]" in text

    def test_stream_tokens_arrive(self):
        """Verify tokens stream through correctly (not batched)."""
        engine = _make_engine()
        app = create_app(engine, "test-model")
        client = TestClient(app)

        resp = client.post(
            "/v1/chat/completions",
            json={
                "model": "test-model",
                "messages": [{"role": "user", "content": "Hello"}],
                "stream": True,
            },
        )
        assert resp.status_code == 200

        # Collect tokens
        tokens = []
        for line in resp.text.strip().split("\n"):
            if line.startswith("data:") and "[DONE]" not in line:
                data = json.loads(line[5:].strip())
                content = data.get("choices", [{}])[0].get("delta", {}).get("content")
                if content:
                    tokens.append(content)

        assert tokens == ["Hello", " ", "world"]

    def test_stream_without_agent_uses_direct_engine(self):
        """When no tools in request, streaming should use engine.stream directly
        even if an agent is configured (for real token-by-token output)."""
        from openjarvis.agents._stubs import AgentResult

        engine = _make_engine()
        agent = MagicMock()
        agent.agent_id = "simple"
        agent.run.return_value = AgentResult(
            content="agent response",
            turns=1,
        )

        app = create_app(engine, "test-model", agent=agent)
        client = TestClient(app)

        resp = client.post(
            "/v1/chat/completions",
            json={
                "model": "test-model",
                "messages": [{"role": "user", "content": "Hello"}],
                "stream": True,
                # No tools — should use direct engine stream
            },
        )
        assert resp.status_code == 200

        # Should get engine tokens, not agent response
        tokens = []
        for line in resp.text.strip().split("\n"):
            if line.startswith("data:") and "[DONE]" not in line:
                data = json.loads(line[5:].strip())
                content = data.get("choices", [{}])[0].get("delta", {}).get("content")
                if content:
                    tokens.append(content)

        assert "".join(tokens) == "Hello world"
        # Agent.run should NOT have been called
        agent.run.assert_not_called()


# ---------------------------------------------------------------------------
# Models endpoint
# ---------------------------------------------------------------------------


class TestModelsEndpointExtended:
    def test_models_list_multiple(self):
        engine = _make_engine(
            models=["qwen3.5:4b", "qwen3.5:9b", "qwen3:0.6b"],
        )
        app = create_app(engine, "qwen3.5:4b")
        client = TestClient(app)
        resp = client.get("/v1/models")
        assert resp.status_code == 200
        ids = [m["id"] for m in resp.json()["data"]]
        assert "qwen3.5:4b" in ids
        assert "qwen3.5:9b" in ids
        assert "qwen3:0.6b" in ids

    def test_models_empty_engine(self):
        """When engine.list_models() returns empty, endpoint still succeeds."""
        engine = _make_engine(models=[])
        app = create_app(engine, "test-model")
        client = TestClient(app)
        resp = client.get("/v1/models")
        assert resp.status_code == 200
        # The endpoint returns whatever list_models() gives
        assert resp.json()["object"] == "list"


class TestCloudAgentRouting:
    class FakeLocalEngine:
        engine_id = "ollama"
        is_cloud = False

        def __init__(self):
            self.generated_models = []

        def health(self):
            return True

        def list_models(self):
            return ["qwen3.5:4b"]

        def generate(self, messages, *, model, **kwargs):
            self.generated_models.append(model)
            return {"content": f"local:{model}", "usage": {}}

        async def stream(self, messages, *, model, **kwargs):
            yield f"local:{model}"

        def close(self):
            pass

    def test_create_app_cloud_auto_attach_updates_agent_engine(self, monkeypatch):
        """Agent streams must use the cloud-aware app engine after startup wrap."""

        class FakeCloudEngine:
            engine_id = "cloud"
            is_cloud = True

            def health(self):
                return True

            def list_models(self):
                return ["gpt-4o"]

            def generate(self, messages, *, model, **kwargs):
                return {"content": f"cloud:{model}", "usage": {}}

            def close(self):
                pass

        import openjarvis.engine.cloud as cloud_module

        monkeypatch.setenv("OPENAI_API_KEY", "test-key")
        monkeypatch.setattr(cloud_module, "CloudEngine", FakeCloudEngine)

        local_engine = self.FakeLocalEngine()
        agent = MagicMock()
        agent._engine = local_engine

        app = create_app(
            local_engine,
            "qwen3.5:4b",
            agent=agent,
            engine_name="ollama",
        )

        assert app.state.engine_name == "multi"
        assert agent._engine is app.state.engine
        result = agent._engine.generate([], model="gpt-4o")
        assert result["content"] == "cloud:gpt-4o"
        assert local_engine.generated_models == []

    def test_cloud_reload_updates_agent_engine(self, monkeypatch):
        """Hot reload must move existing agents off the stale Ollama engine."""

        class FakeCloudEngine:
            engine_id = "cloud"
            is_cloud = True

            def health(self):
                return True

            def list_models(self):
                return ["gpt-4o"]

            def generate(self, messages, *, model, **kwargs):
                return {"content": f"cloud:{model}", "usage": {}}

            def close(self):
                pass

        import openjarvis.engine.cloud as cloud_module

        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.setattr(cloud_module, "CloudEngine", FakeCloudEngine)

        local_engine = self.FakeLocalEngine()
        agent = MagicMock()
        agent._engine = local_engine
        app = create_app(
            local_engine,
            "qwen3.5:4b",
            agent=agent,
            engine_name="ollama",
        )
        client = TestClient(app)

        resp = client.post("/v1/cloud/reload")

        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"
        assert app.state.engine_name == "multi"
        assert agent._engine is app.state.engine
        result = agent._engine.generate([], model="gpt-4o")
        assert result["content"] == "cloud:gpt-4o"
        assert local_engine.generated_models == []

    def test_save_cloud_key_writes_file_and_updates_agent_engine(
        self,
        monkeypatch,
        tmp_path,
    ):
        """Browser key saves must reach the Python server, not only localStorage."""

        class FakeCloudEngine:
            engine_id = "cloud"
            is_cloud = True

            def health(self):
                return True

            def list_models(self):
                return ["gpt-4o"]

            def generate(self, messages, *, model, **kwargs):
                return {"content": f"cloud:{model}", "usage": {}}

            def close(self):
                pass

        import pathlib

        import openjarvis.engine.cloud as cloud_module

        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.setattr(pathlib.Path, "home", lambda: tmp_path)
        monkeypatch.setattr(cloud_module, "CloudEngine", FakeCloudEngine)
        (tmp_path / ".openjarvis").mkdir()

        local_engine = self.FakeLocalEngine()
        agent = MagicMock()
        agent._engine = local_engine
        app = create_app(
            local_engine,
            "qwen3.5:4b",
            agent=agent,
            engine_name="ollama",
        )
        client = TestClient(app)

        resp = client.post(
            "/v1/cloud/keys",
            json={"keyName": "OPENAI_API_KEY", "keyValue": "sk-test"},
        )

        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"
        keys_path = tmp_path / ".openjarvis" / "cloud-keys.env"
        assert keys_path.read_text() == "OPENAI_API_KEY=sk-test\n"
        assert agent._engine is app.state.engine
        result = agent._engine.generate([], model="gpt-4o")
        assert result["content"] == "cloud:gpt-4o"
        assert local_engine.generated_models == []

    def test_cloud_stream_bypasses_agent_ollama_engine(self, monkeypatch):
        """Cloud chat streams should not pass through an Ollama-backed agent."""

        async def fake_stream_cloud(model, messages, temperature, max_tokens):
            yield f"cloud:{model}"

        import openjarvis.server.cloud_router as cloud_router

        monkeypatch.setattr(cloud_router, "stream_cloud", fake_stream_cloud)

        local_engine = self.FakeLocalEngine()
        agent = MagicMock()
        agent._engine = local_engine

        app = create_app(
            local_engine,
            "qwen3.5:4b",
            agent=agent,
            bus=MagicMock(),
            engine_name="ollama",
        )
        client = TestClient(app)

        resp = client.post(
            "/v1/chat/completions",
            json={
                "model": "gpt-4o-mini",
                "messages": [{"role": "user", "content": "hello"}],
                "stream": True,
            },
        )

        assert resp.status_code == 200
        assert "cloud:gpt-4o-mini" in resp.text
        agent.run.assert_not_called()
        assert local_engine.generated_models == []

    def test_removing_cloud_key_detaches_stale_cloud_engine(
        self,
        monkeypatch,
        tmp_path,
    ):
        """Switching back to local must remove cloud routing from MultiEngine."""

        class FakeCloudEngine:
            engine_id = "cloud"
            is_cloud = True

            def health(self):
                import os

                return bool(os.environ.get("OPENAI_API_KEY"))

            def list_models(self):
                return ["gpt-4o"]

            def generate(self, messages, *, model, **kwargs):
                return {"content": f"cloud:{model}", "usage": {}}

            def close(self):
                pass

        import pathlib

        import openjarvis.engine.cloud as cloud_module

        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.setattr(pathlib.Path, "home", lambda: tmp_path)
        monkeypatch.setattr(cloud_module, "CloudEngine", FakeCloudEngine)
        (tmp_path / ".openjarvis").mkdir()

        local_engine = self.FakeLocalEngine()
        agent = MagicMock()
        agent._engine = local_engine
        app = create_app(
            local_engine,
            "qwen3.5:4b",
            agent=agent,
            engine_name="ollama",
        )
        client = TestClient(app)

        add_resp = client.post(
            "/v1/cloud/keys",
            json={"keyName": "OPENAI_API_KEY", "keyValue": "sk-test"},
        )
        assert add_resp.status_code == 200
        assert add_resp.json()["status"] == "ok"
        assert app.state.engine_name == "multi"

        remove_resp = client.post(
            "/v1/cloud/keys",
            json={"keyName": "OPENAI_API_KEY", "keyValue": ""},
        )

        assert remove_resp.status_code == 200
        assert remove_resp.json()["status"] == "no_cloud"
        assert app.state.engine_name == "ollama"
        assert app.state.engine is local_engine
        assert agent._engine is local_engine
        assert "OPENAI_API_KEY" not in __import__("os").environ
