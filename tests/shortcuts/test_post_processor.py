"""Unit tests for shortcut post-processor prompt and model precedence."""

from __future__ import annotations

from typing import Any, Dict, List

from openjarvis.shortcuts import post_processor
from openjarvis.shortcuts._stubs import RawResult


class _FakeEngine:
    def __init__(self, content: str = "rewritten", fail: bool = False) -> None:
        self._content = content
        self._fail = fail
        self.calls: List[Dict[str, Any]] = []

    def generate(self, messages, *, model, temperature=0.7, max_tokens=1024, **kwargs):
        self.calls.append(
            {
                "messages": [(m.role, m.content) for m in messages],
                "model": model,
            }
        )
        if self._fail:
            raise RuntimeError("boom")
        return {"content": self._content, "usage": {}}


def test_passthrough_when_no_prompt_anywhere():
    raw = RawResult(content="hello", success=True)
    out = post_processor.run(
        raw,
        rule_prompt=None,
        default_prompt_from_target=None,
        engine=_FakeEngine(),
        model="m",
    )
    assert out.success is True
    assert out.content == "hello"
    assert out.used_prompt is None


def test_empty_string_rule_prompt_forces_passthrough_even_with_target_default():
    raw = RawResult(content="hello", success=True)
    out = post_processor.run(
        raw,
        rule_prompt="",
        default_prompt_from_target="rewrite as a haiku",
        engine=_FakeEngine(),
        model="m",
    )
    assert out.content == "hello"
    assert out.used_prompt is None


def test_target_default_used_when_rule_prompt_unset():
    engine = _FakeEngine(content="haiku")
    raw = RawResult(content="hello", success=True)
    out = post_processor.run(
        raw,
        rule_prompt=None,
        default_prompt_from_target="rewrite as a haiku",
        engine=engine,
        model="m",
    )
    assert out.success
    assert out.content == "haiku"
    assert engine.calls[0]["messages"][0] == ("system", "rewrite as a haiku")


def test_rule_prompt_overrides_target_default():
    engine = _FakeEngine(content="ok")
    raw = RawResult(content="hello", success=True)
    out = post_processor.run(
        raw,
        rule_prompt="rule wins",
        default_prompt_from_target="target default",
        engine=engine,
        model="m",
    )
    assert engine.calls[0]["messages"][0] == ("system", "rule wins")
    assert out.used_prompt == "rule wins"


def test_engine_failure_falls_back_to_raw():
    raw = RawResult(content="raw content", success=True)
    out = post_processor.run(
        raw,
        rule_prompt="rewrite please",
        default_prompt_from_target=None,
        engine=_FakeEngine(fail=True),
        model="m",
    )
    assert out.success is False
    assert out.content == "raw content"
    assert out.error and "boom" in out.error


def test_empty_engine_response_falls_back_to_raw():
    raw = RawResult(content="raw", success=True)
    out = post_processor.run(
        raw,
        rule_prompt="rewrite",
        default_prompt_from_target=None,
        engine=_FakeEngine(content="   "),
        model="m",
    )
    assert out.success is False
    assert out.content == "raw"
    assert out.error == "empty_response"


def test_missing_engine_is_handled():
    raw = RawResult(content="raw", success=True)
    out = post_processor.run(
        raw,
        rule_prompt="rewrite",
        default_prompt_from_target=None,
        engine=None,
        model="m",
    )
    assert out.success is False
    assert out.content == "raw"
    assert out.error == "no_engine_or_model"
