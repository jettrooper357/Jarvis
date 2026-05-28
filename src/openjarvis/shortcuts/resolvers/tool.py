"""Tool resolver — runs a tool from :class:`ToolRegistry` and normalizes the result."""

from __future__ import annotations

from typing import Any, Dict

from openjarvis.core.registry import ToolRegistry
from openjarvis.shortcuts._stubs import RawResult, Resolver


class ToolResolver(Resolver):
    """Resolve a rule that targets ``target_kind = "tool"``."""

    kind = "tool"

    def resolve(self, target_id: str, args: Dict[str, Any]) -> RawResult:
        try:
            tool_cls = ToolRegistry.get(target_id)
        except KeyError:
            return RawResult(
                content=f"Unknown tool: {target_id}",
                success=False,
                error="unknown_tool",
            )
        if tool_cls is None:
            return RawResult(
                content=f"Unknown tool: {target_id}",
                success=False,
                error="unknown_tool",
            )
        try:
            tool = tool_cls()
        except Exception as exc:  # pragma: no cover — defensive
            return RawResult(
                content=f"Tool instantiation failed: {exc}",
                success=False,
                error="tool_init_failed",
            )

        default_post_prompt = None
        try:
            spec = tool.spec
            metadata = getattr(spec, "metadata", {}) or {}
            default_post_prompt = metadata.get("default_post_prompt")
        except Exception:
            default_post_prompt = None

        try:
            result = tool.execute(**args)
        except Exception as exc:
            return RawResult(
                content=f"Tool execution error: {exc}",
                success=False,
                error="tool_execution_error",
                default_post_prompt=default_post_prompt,
            )

        return RawResult(
            content=str(result.content or ""),
            success=bool(result.success),
            metadata=dict(result.metadata or {}),
            default_post_prompt=default_post_prompt,
            error=None if result.success else (result.metadata or {}).get("error"),
        )


__all__ = ["ToolResolver"]
