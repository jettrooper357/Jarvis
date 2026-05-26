"""News convenience tools."""

from __future__ import annotations

from datetime import date
from typing import Any

from openjarvis.core.registry import ToolRegistry
from openjarvis.core.types import ToolResult
from openjarvis.tools._stubs import BaseTool, ToolSpec
from openjarvis.tools.web_search import WebSearchTool


@ToolRegistry.register("get_todays_news")
class GetTodaysNewsTool(BaseTool):
    """Compatibility tool for models that ask for today's news directly."""

    tool_id = "get_todays_news"
    is_local = False

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="get_todays_news",
            description=(
                "Get current top news headlines. Use with no arguments for a "
                "general briefing, or pass a topic for focused news."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "topic": {
                        "type": "string",
                        "description": "Optional topic, region, or beat.",
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Maximum number of results to return.",
                    },
                },
            },
            category="search",
            required_capabilities=["network:fetch"],
        )

    def execute(self, **params: Any) -> ToolResult:
        topic = str(params.get("topic") or "").strip()
        max_results = int(params.get("max_results") or 8)
        today = date.today().isoformat()
        query = (
            f"top news today {today}"
            if not topic
            else f"top news today {today} {topic}"
        )
        result = WebSearchTool(max_results=max_results).execute(
            query=query,
            max_results=max_results,
        )
        return ToolResult(
            tool_name="get_todays_news",
            content=result.content,
            success=result.success,
            metadata={
                **(result.metadata or {}),
                "query": query,
                "topic": topic,
                "date": today,
            },
        )


@ToolRegistry.register("get_news")
class GetNewsTool(GetTodaysNewsTool):
    """Alias for :class:`GetTodaysNewsTool` under the short name models reach for.

    Registered separately so the tool registry resolves either name; the
    spec advertises ``get_news`` so the prompt and runtime stay aligned.
    """

    tool_id = "get_news"

    @property
    def spec(self) -> ToolSpec:
        base = super().spec
        return ToolSpec(
            name="get_news",
            description=base.description,
            parameters=base.parameters,
            category=base.category,
            required_capabilities=base.required_capabilities,
        )

    def execute(self, **params: Any) -> ToolResult:
        result = super().execute(**params)
        return ToolResult(
            tool_name="get_news",
            content=result.content,
            success=result.success,
            metadata=result.metadata,
        )


__all__ = ["GetTodaysNewsTool", "GetNewsTool"]
