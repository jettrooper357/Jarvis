from __future__ import annotations


def test_get_todays_news_registered():
    from openjarvis.tools.news import GetTodaysNewsTool
    from openjarvis.core.registry import ToolRegistry

    if not ToolRegistry.contains("get_todays_news"):
        ToolRegistry.register_value("get_todays_news", GetTodaysNewsTool)
    assert ToolRegistry.contains("get_todays_news")
    tool = ToolRegistry.get("get_todays_news")()
    assert tool.spec.name == "get_todays_news"
    assert "topic" in tool.spec.parameters["properties"]
