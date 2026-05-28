"""End-to-end integration tests for the Chief pre-turn shortcut hook.

These tests assemble a real :class:`OrchestratorAgent` (function-calling
mode), wire a fake :class:`InferenceEngine`, point the agent at a
registered shortcut rule, and assert:

1. A matching shortcut short-circuits the Chief LLM call entirely
   (``engine.generate`` is never invoked for the decision turn).
2. The shortcut content is returned in :class:`AgentResult.content`
   with shortcut metadata attached.
3. A resolver failure with ``on_failure='fallback_to_chief'`` causes
   the Chief to run its normal LLM path.
4. A resolver failure with ``on_failure='error'`` is terminal.

Tests use a stub engine to avoid any network / model dependency.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Sequence

import pytest

from openjarvis.agents.orchestrator import OrchestratorAgent
from openjarvis.core.types import Message
from openjarvis.shortcuts import ShortcutRegistry, try_shortcut
from openjarvis.shortcuts._stubs import PatternSpec, RawResult, Resolver, ShortcutRule


def _ts() -> str:
    return datetime.now(timezone.utc).isoformat()


class _StubEngine:
    """Minimal :class:`InferenceEngine` stand-in that records calls."""

    engine_id = "stub"
    is_cloud = False

    def __init__(self, content: str = "chief-fallback-answer") -> None:
        self._content = content
        self.calls: List[Dict[str, Any]] = []

    def generate(
        self,
        messages: Sequence[Message],
        *,
        model: str,
        temperature: float = 0.7,
        max_tokens: int = 1024,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        self.calls.append(
            {
                "model": model,
                "messages": [(m.role, m.content) for m in messages],
            }
        )
        return {
            "content": self._content,
            "usage": {"prompt_tokens": 1, "completion_tokens": 1},
            "tool_calls": [],
        }

    async def stream(self, *_args: Any, **_kwargs: Any):  # pragma: no cover — unused
        yield ""

    def list_models(self) -> List[str]:
        return ["stub-model"]

    def health(self) -> bool:
        return True


class _OkResolver(Resolver):
    kind = "tool"

    def resolve(self, target_id: str, args: Dict[str, Any]) -> RawResult:
        return RawResult(content="resolver-content", success=True)


class _FailResolver(Resolver):
    kind = "tool"

    def resolve(self, target_id: str, args: Dict[str, Any]) -> RawResult:
        return RawResult(content="boom", success=False, error="resolver_failed")


@pytest.fixture()
def registry(tmp_path: Path) -> ShortcutRegistry:
    return ShortcutRegistry(db_path=tmp_path / "sc.db")


def _make_rule(*, on_failure: str = "fallback_to_chief") -> ShortcutRule:
    return ShortcutRule(
        id="r1",
        name="hello-rule",
        patterns=[PatternSpec("phrase", "hello")],
        target_kind="tool",
        target_id="get_news",
        on_failure=on_failure,
        created_at=_ts(),
        updated_at=_ts(),
    )


def _hook(registry: ShortcutRegistry, resolver: Resolver):
    def _h(user_message: str):
        return try_shortcut(
            user_message,
            registry=registry,
            resolvers={resolver.kind: resolver},
        )

    return _h


def test_matching_shortcut_skips_chief_llm_call(registry):
    registry.upsert(_make_rule())
    engine = _StubEngine()
    agent = OrchestratorAgent(
        engine=engine,
        model="stub-model",
        tools=[],
        mode="function_calling",
        pre_turn_hook=_hook(registry, _OkResolver()),
    )

    result = agent.run("hello there")

    assert result.content == "resolver-content"
    assert engine.calls == []  # Chief LLM never invoked
    assert result.metadata["shortcut"]["rule_name"] == "hello-rule"
    assert result.metadata["shortcut"]["success"] is True


def test_fallback_to_chief_runs_normal_llm_turn(registry):
    registry.upsert(_make_rule(on_failure="fallback_to_chief"))
    engine = _StubEngine(content="chief-said-this")
    agent = OrchestratorAgent(
        engine=engine,
        model="stub-model",
        tools=[],
        mode="function_calling",
        pre_turn_hook=_hook(registry, _FailResolver()),
    )

    result = agent.run("hello there")

    assert result.content == "chief-said-this"
    assert len(engine.calls) == 1  # Chief LLM did run because of fallback


def test_on_failure_error_short_circuits_with_error_message(registry):
    registry.upsert(_make_rule(on_failure="error"))
    engine = _StubEngine()
    agent = OrchestratorAgent(
        engine=engine,
        model="stub-model",
        tools=[],
        mode="function_calling",
        pre_turn_hook=_hook(registry, _FailResolver()),
    )

    result = agent.run("hello there")

    assert engine.calls == []
    assert "failed" in result.content.lower()
    assert result.metadata["shortcut"]["success"] is False


def test_no_match_runs_chief_normally(registry):
    registry.upsert(_make_rule())
    engine = _StubEngine(content="ordinary-chief-answer")
    agent = OrchestratorAgent(
        engine=engine,
        model="stub-model",
        tools=[],
        mode="function_calling",
        pre_turn_hook=_hook(registry, _OkResolver()),
    )

    result = agent.run("totally unrelated question")

    assert result.content == "ordinary-chief-answer"
    assert len(engine.calls) == 1


def test_hook_exception_does_not_break_chief(registry):
    def _bad_hook(_msg: str):
        raise RuntimeError("hook explodes")

    engine = _StubEngine(content="resilient-chief")
    agent = OrchestratorAgent(
        engine=engine,
        model="stub-model",
        tools=[],
        mode="function_calling",
        pre_turn_hook=_bad_hook,
    )

    result = agent.run("anything")
    assert result.content == "resilient-chief"
    assert len(engine.calls) == 1
