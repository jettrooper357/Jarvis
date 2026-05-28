"""Unit tests for PresetResolver."""

from __future__ import annotations

from typing import Any, Dict, List

from openjarvis.shortcuts.resolvers.preset import PresetResolver


class _FakeEngine:
    def __init__(self, content: str = "ok", fail: bool = False) -> None:
        self._content = content
        self._fail = fail
        self.calls: List[Dict[str, Any]] = []

    def generate(self, messages, *, model, temperature=0.7, max_tokens=1024, **kwargs):
        self.calls.append(
            {
                "model": model,
                "messages": [(m.role, m.content) for m in messages],
            }
        )
        if self._fail:
            raise RuntimeError("engine boom")
        return {"content": self._content, "usage": {}}


def _patch_template(monkeypatch, *, template: Dict[str, Any], missing: bool = False):
    def fake_get(_id):
        if missing:
            raise FileNotFoundError(_id)
        return {"content": "ignored"}

    def fake_parse(_content):
        return template

    monkeypatch.setattr("openjarvis.agents.library.get_template_document", fake_get)
    monkeypatch.setattr("openjarvis.agents.library.parse_template_content", fake_parse)


def test_happy_path_renders_system_prompt_with_instruction(monkeypatch):
    _patch_template(
        monkeypatch,
        template={
            "id": "p1",
            "system_prompt_template": "Persona: pirate. Task: {instruction}",
            "temperature": 0.2,
            "max_tokens": 256,
        },
    )
    engine = _FakeEngine(content="Arrr!")
    res = PresetResolver(engine=engine, model="m").resolve(
        "p1", {"instruction": "tell a joke"}
    )
    assert res.success
    assert res.content == "Arrr!"
    system_msg = engine.calls[0]["messages"][0]
    assert "Persona: pirate" in system_msg[1]
    assert "tell a joke" in system_msg[1]


def test_unknown_preset_returns_error(monkeypatch):
    _patch_template(monkeypatch, template={}, missing=True)
    res = PresetResolver(engine=_FakeEngine(), model="m").resolve("nope", {})
    assert res.success is False
    assert res.error == "unknown_preset"


def test_missing_engine_returns_no_engine(monkeypatch):
    _patch_template(monkeypatch, template={"system_prompt_template": "hi"})
    res = PresetResolver(engine=None, model="m").resolve("p1", {})
    assert res.success is False
    assert res.error == "no_engine"


def test_engine_failure_is_captured(monkeypatch):
    _patch_template(monkeypatch, template={"system_prompt_template": "hi"})
    res = PresetResolver(engine=_FakeEngine(fail=True), model="m").resolve(
        "p1", {"instruction": "x"}
    )
    assert res.success is False
    assert res.error == "preset_run_failed"


def test_empty_response_returns_empty_response_error(monkeypatch):
    _patch_template(monkeypatch, template={"system_prompt_template": "hi"})
    res = PresetResolver(engine=_FakeEngine(content=" "), model="m").resolve("p1", {})
    assert res.success is False
    assert res.error == "empty_response"
