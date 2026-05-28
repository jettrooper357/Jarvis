"""Unit tests for the tool resolver."""

from __future__ import annotations

from typing import Any

from openjarvis.core.registry import ToolRegistry
from openjarvis.core.types import ToolResult
from openjarvis.shortcuts.resolvers.tool import ToolResolver
from openjarvis.tools._stubs import BaseTool, ToolSpec


def _register_fake_tool(
    name: str,
    *,
    content: str = "ok",
    success: bool = True,
    default_post_prompt: str | None = None,
    raise_exc: bool = False,
):
    metadata: dict[str, Any] = {}
    if default_post_prompt is not None:
        metadata["default_post_prompt"] = default_post_prompt

    @ToolRegistry.register(name)
    class _FakeTool(BaseTool):  # type: ignore[misc]
        tool_id = name

        @property
        def spec(self) -> ToolSpec:
            return ToolSpec(
                name=name,
                description="fake",
                parameters={"type": "object", "properties": {}},
                metadata=metadata,
            )

        def execute(self, **params: Any) -> ToolResult:
            if raise_exc:
                raise RuntimeError("kaboom")
            return ToolResult(
                tool_name=name,
                content=content,
                success=success,
                metadata={"args": params},
            )

    return _FakeTool


def test_tool_resolver_happy_path(monkeypatch):
    _register_fake_tool("sc_fake_ok", content="hello", default_post_prompt="rewrite!")
    result = ToolResolver().resolve("sc_fake_ok", {"topic": "x"})
    assert result.success is True
    assert result.content == "hello"
    assert result.default_post_prompt == "rewrite!"
    assert result.metadata["args"] == {"topic": "x"}


def test_tool_resolver_unknown_tool():
    result = ToolResolver().resolve("definitely_not_a_real_tool", {})
    assert result.success is False
    assert result.error == "unknown_tool"


def test_tool_resolver_propagates_tool_failure():
    _register_fake_tool("sc_fake_fail", content="nope", success=False)
    result = ToolResolver().resolve("sc_fake_fail", {})
    assert result.success is False
    assert result.content == "nope"


def test_tool_resolver_catches_exception():
    _register_fake_tool("sc_fake_raise", raise_exc=True)
    result = ToolResolver().resolve("sc_fake_raise", {})
    assert result.success is False
    assert result.error == "tool_execution_error"
    assert "kaboom" in result.content
