from __future__ import annotations


def test_get_todays_news_registered():
    from openjarvis.core.registry import ToolRegistry
    from openjarvis.tools.news import GetNewsTool, GetTodaysNewsTool

    if not ToolRegistry.contains("get_todays_news"):
        ToolRegistry.register_value("get_todays_news", GetTodaysNewsTool)
    if not ToolRegistry.contains("get_news"):
        ToolRegistry.register_value("get_news", GetNewsTool)
    assert ToolRegistry.contains("get_todays_news")
    assert ToolRegistry.contains("get_news")
    tool = ToolRegistry.get("get_todays_news")()
    assert tool.spec.name == "get_todays_news"
    assert "topic" in tool.spec.parameters["properties"]

    alias = ToolRegistry.get("get_news")()
    assert alias.spec.name == "get_news"


def test_get_news_uses_indexed_rss(monkeypatch, tmp_path):
    import sqlite3

    from openjarvis.tools import news
    from openjarvis.tools.news import GetNewsTool

    db_path = tmp_path / "knowledge.db"
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE knowledge_chunks (
            title TEXT,
            content TEXT,
            url TEXT,
            timestamp TEXT,
            metadata TEXT,
            source TEXT,
            created_at REAL
        )
        """
    )
    conn.execute(
        """
        INSERT INTO knowledge_chunks
            (title, content, url, timestamp, metadata, source, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "Local headline",
            "Short summary",
            "https://example.com/news",
            "2026-05-26T10:00:00+00:00",
            '{"feed_name": "Example Feed"}',
            "news_rss",
            1.0,
        ),
    )
    conn.commit()
    conn.close()

    monkeypatch.setattr(news, "_KNOWLEDGE_DB_PATH", db_path)
    result = GetNewsTool().execute()

    assert result.success is True
    assert result.metadata["mode"] == "indexed"
    assert "Local headline" in result.content
    assert "Rewrite these as a concise news-caster narration" in result.content


def test_get_news_live_rss_is_fast_path(monkeypatch, tmp_path):
    from openjarvis.tools import news
    from openjarvis.tools.news import GetNewsTool

    config_path = tmp_path / "news_rss.json"
    config_path.write_text(
        '{"feeds": [{"name": "Example Feed", "url": "https://example.com/rss"}]}',
        encoding="utf-8",
    )

    class _Response:
        text = (
            "<rss><channel><item><title>Live headline</title>"
            "<description>Live summary</description>"
            "<link>https://example.com/live</link>"
            "<pubDate>Tue, 26 May 2026 10:00:00 GMT</pubDate>"
            "</item></channel></rss>"
        )

        def raise_for_status(self) -> None:
            return None

    class _Client:
        def __init__(self, *args, **kwargs):
            self.kwargs = kwargs

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def get(self, url):
            assert url == "https://example.com/rss"
            return _Response()

    monkeypatch.setattr(news, "_KNOWLEDGE_DB_PATH", tmp_path / "missing.db")
    monkeypatch.setattr(news, "_RSS_CONFIG_PATH", config_path)
    monkeypatch.setattr(news.httpx, "Client", _Client)

    result = GetNewsTool().execute()

    assert result.success is True
    assert result.metadata["mode"] == "live"
    assert "Live headline" in result.content
