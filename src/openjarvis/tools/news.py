"""News convenience tools."""

from __future__ import annotations

import json
import re
import sqlite3
import xml.etree.ElementTree as ET
from datetime import date
from email.utils import parsedate_to_datetime
from html import unescape
from pathlib import Path
from typing import Any

import httpx

from openjarvis.core.config import DEFAULT_CONFIG_DIR
from openjarvis.core.registry import ToolRegistry
from openjarvis.core.types import ToolResult
from openjarvis.tools._stubs import BaseTool, ToolSpec

_RSS_CONFIG_PATH = DEFAULT_CONFIG_DIR / "connectors" / "news_rss.json"
_KNOWLEDGE_DB_PATH = DEFAULT_CONFIG_DIR / "knowledge.db"


def _clean_text(value: str, limit: int = 280) -> str:
    text = re.sub(r"<[^>]+>", " ", value or "")
    text = re.sub(r"\s+", " ", unescape(text)).strip()
    if len(text) > limit:
        return text[: limit - 1].rstrip() + "..."
    return text


def _load_recent_indexed_news(max_results: int) -> list[dict[str, str]]:
    if not _KNOWLEDGE_DB_PATH.exists():
        return []
    try:
        conn = sqlite3.connect(str(_KNOWLEDGE_DB_PATH))
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT title, content, url, timestamp, metadata
            FROM knowledge_chunks
            WHERE source = 'news_rss'
            ORDER BY timestamp DESC, created_at DESC
            LIMIT ?
            """,
            (max_results,),
        ).fetchall()
    except sqlite3.Error:
        return []
    finally:
        try:
            conn.close()
        except Exception:
            pass

    items: list[dict[str, str]] = []
    for row in rows:
        metadata = {}
        try:
            metadata = json.loads(row["metadata"] or "{}")
        except json.JSONDecodeError:
            metadata = {}
        items.append(
            {
                "title": row["title"] or "Untitled",
                "description": _clean_text(row["content"] or ""),
                "link": row["url"] or "",
                "published": row["timestamp"] or "",
                "feed": str(metadata.get("feed_name") or "News / RSS"),
            }
        )
    return items


def _parse_feed_items(xml_text: str, feed_name: str, max_items: int) -> list[dict[str, str]]:
    root = ET.fromstring(xml_text)
    items: list[dict[str, str]] = []

    for item_el in root.iter("item"):
        if len(items) >= max_items:
            break
        items.append(
            {
                "title": _clean_text(item_el.findtext("title") or "", 180) or "Untitled",
                "description": _clean_text(item_el.findtext("description") or ""),
                "link": (item_el.findtext("link") or "").strip(),
                "published": (item_el.findtext("pubDate") or "").strip(),
                "feed": feed_name,
            }
        )

    if not items:
        ns = {"atom": "http://www.w3.org/2005/Atom"}
        for entry_el in root.iter("{http://www.w3.org/2005/Atom}entry"):
            if len(items) >= max_items:
                break
            link_el = entry_el.find("atom:link", ns)
            items.append(
                {
                    "title": _clean_text(
                        entry_el.findtext("{http://www.w3.org/2005/Atom}title") or "",
                        180,
                    )
                    or "Untitled",
                    "description": _clean_text(
                        entry_el.findtext("{http://www.w3.org/2005/Atom}summary") or ""
                    ),
                    "link": (link_el.get("href", "") if link_el is not None else "").strip(),
                    "published": (
                        entry_el.findtext("{http://www.w3.org/2005/Atom}updated") or ""
                    ).strip(),
                    "feed": feed_name,
                }
            )
    return items


def _published_sort_key(item: dict[str, str]) -> str:
    raw = item.get("published", "")
    if not raw:
        return ""
    try:
        return parsedate_to_datetime(raw).isoformat()
    except (TypeError, ValueError):
        return raw


def _load_live_rss_news(max_results: int) -> list[dict[str, str]]:
    if not _RSS_CONFIG_PATH.exists():
        return []
    try:
        config = json.loads(Path(_RSS_CONFIG_PATH).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    feeds = config.get("feeds") or []
    if not isinstance(feeds, list):
        return []

    items: list[dict[str, str]] = []
    per_feed = max(1, min(max_results, int(config.get("max_items_per_feed", 6) or 6)))
    with httpx.Client(
        timeout=httpx.Timeout(5.0, connect=2.0),
        follow_redirects=True,
        headers={
            "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml;q=0.9, */*;q=0.8",
            "User-Agent": "OpenJarvis/1.0 (+https://open-jarvis.github.io/OpenJarvis/)",
        },
    ) as client:
        for feed in feeds[:8]:
            if not isinstance(feed, dict):
                continue
            url = str(feed.get("url") or "").strip()
            if not url:
                continue
            name = str(feed.get("name") or url)
            try:
                response = client.get(url)
                response.raise_for_status()
                items.extend(_parse_feed_items(response.text, name, per_feed))
            except (httpx.HTTPError, ET.ParseError):
                continue
            if len(items) >= max_results:
                break

    return sorted(items, key=_published_sort_key, reverse=True)[:max_results]


def _format_news(items: list[dict[str, str]], *, source: str) -> str:
    lines = [
        f"Today's RSS headlines ({source}). Rewrite these as a concise news-caster narration:",
    ]
    for index, item in enumerate(items, 1):
        lines.append(
            "\n".join(
                part
                for part in [
                    f"{index}. {item.get('title', 'Untitled')}",
                    f"   Feed: {item.get('feed', 'News / RSS')}",
                    f"   Published: {item.get('published', '')}" if item.get("published") else "",
                    f"   Summary: {item.get('description', '')}" if item.get("description") else "",
                    f"   Link: {item.get('link', '')}" if item.get("link") else "",
                ]
                if part
            )
        )
    return "\n".join(lines)


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
                "Get current top news headlines from the configured News/RSS source. "
                "Use with no arguments for a general briefing."
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
            timeout_seconds=8.0,
            required_capabilities=["network:fetch"],
            metadata={
                "source": "news_rss",
                "default_post_prompt": (
                    "You are a concise news-caster. Rewrite the headlines "
                    "below as a neutral, professional spoken briefing for "
                    "the user. Keep proper names, organizations, and dates "
                    "accurate. Group related items, drop duplicates, and "
                    "skip filler. Target 4–6 sentences total. Do not add "
                    "facts that are not present in the source items."
                ),
            },
        )

    def execute(self, **params: Any) -> ToolResult:
        topic = str(params.get("topic") or "").strip()
        max_results = int(params.get("max_results") or 8)
        today = date.today().isoformat()
        indexed = _load_recent_indexed_news(max_results)
        items = indexed or _load_live_rss_news(max_results)
        if topic:
            needle = topic.lower()
            items = [
                item
                for item in items
                if needle in item.get("title", "").lower()
                or needle in item.get("description", "").lower()
                or needle in item.get("feed", "").lower()
            ]
        if not items:
            return ToolResult(
                tool_name=self.tool_id,
                content=(
                    "No News/RSS headlines are available yet. Configure or sync the "
                    "News / RSS data source, then ask again."
                ),
                success=False,
                metadata={"topic": topic, "date": today, "source": "news_rss"},
            )
        source = "indexed News/RSS" if indexed else "live RSS fetch"
        return ToolResult(
            tool_name=self.tool_id,
            content=_format_news(items[:max_results], source=source),
            success=True,
            metadata={
                "topic": topic,
                "date": today,
                "source": "news_rss",
                "mode": "indexed" if indexed else "live",
                "num_results": len(items[:max_results]),
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
