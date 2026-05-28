"""Unit tests for SkillResolver."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

from openjarvis.shortcuts.resolvers.skill import SkillResolver


@dataclass
class _FakeStepResult:
    content: str = ""


@dataclass
class _FakeSkillResult:
    skill_name: str = ""
    success: bool = True
    step_results: List[_FakeStepResult] = field(default_factory=list)
    context: Dict[str, Any] = field(default_factory=dict)


class _FakeManifest:
    def __init__(self, name: str, *, default_post_prompt: str | None = None) -> None:
        self.name = name
        self.metadata = (
            {"default_post_prompt": default_post_prompt}
            if default_post_prompt is not None
            else {}
        )


class _FakeManager:
    def __init__(
        self, *, manifest=None, result=None, raise_resolve=False, raise_execute=False
    ):
        self._manifest = manifest
        self._result = result
        self._raise_resolve = raise_resolve
        self._raise_execute = raise_execute
        self.last_context: Dict[str, Any] | None = None

    def resolve(self, name: str):
        if self._raise_resolve:
            raise RuntimeError("missing skill")
        return self._manifest

    def execute(self, name: str, context=None):
        self.last_context = dict(context or {})
        if self._raise_execute:
            raise RuntimeError("kaboom")
        return self._result


def test_happy_path_returns_last_step_and_post_prompt():
    mgr = _FakeManager(
        manifest=_FakeManifest("s1", default_post_prompt="rewrite!"),
        result=_FakeSkillResult(
            skill_name="s1",
            success=True,
            step_results=[
                _FakeStepResult("step1"),
                _FakeStepResult("step2-final"),
            ],
        ),
    )
    res = SkillResolver(manager=mgr).resolve("s1", {"foo": "bar"})
    assert res.success
    assert res.content == "step2-final"
    assert res.default_post_prompt == "rewrite!"
    assert mgr.last_context == {"foo": "bar"}


def test_unknown_skill_reports_error():
    mgr = _FakeManager(raise_resolve=True)
    res = SkillResolver(manager=mgr).resolve("nope", {})
    assert res.success is False
    assert res.error == "unknown_skill"


def test_execution_exception_is_captured():
    mgr = _FakeManager(
        manifest=_FakeManifest("s1"),
        raise_execute=True,
    )
    res = SkillResolver(manager=mgr).resolve("s1", {})
    assert res.success is False
    assert res.error == "skill_execution_error"


def test_falls_back_to_joined_steps_when_last_is_empty():
    mgr = _FakeManager(
        manifest=_FakeManifest("s1"),
        result=_FakeSkillResult(
            success=True,
            step_results=[
                _FakeStepResult("alpha"),
                _FakeStepResult("beta"),
                _FakeStepResult(""),
            ],
        ),
    )
    res = SkillResolver(manager=mgr).resolve("s1", {})
    assert res.success
    assert "alpha" in res.content and "beta" in res.content
