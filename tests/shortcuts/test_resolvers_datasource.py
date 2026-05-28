"""Unit tests for DataSourceResolver."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

from openjarvis.shortcuts.resolvers.datasource import DataSourceResolver


@dataclass
class _Row:
    content: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)


class _FakeStore:
    def __init__(self, rows: List[_Row], *, raise_first: bool = False) -> None:
        self._rows = rows
        self._raise_first = raise_first
        self.calls: List[Dict[str, Any]] = []

    def retrieve(self, query: str, **kwargs: Any) -> List[_Row]:
        self.calls.append({"query": query, **kwargs})
        if self._raise_first and len(self.calls) == 1:
            raise RuntimeError("FTS rejected")
        return list(self._rows)

    def close(self) -> None:  # pragma: no cover — best-effort close
        pass


def test_returns_formatted_results_for_source():
    store = _FakeStore(
        rows=[
            _Row(
                content="alpha news",
                metadata={"title": "Alpha", "timestamp": "2026-05-27"},
            ),
            _Row(
                content="beta news",
                metadata={"title": "Beta", "timestamp": "2026-05-27"},
            ),
        ]
    )
    resolver = DataSourceResolver(store_factory=lambda: store)
    res = resolver.resolve("news_rss", {"top_k": 2})
    assert res.success
    assert "Alpha" in res.content and "Beta" in res.content
    assert store.calls[0]["source"] == "news_rss"
    assert store.calls[0]["top_k"] == 2


def test_empty_result_returns_no_results_error():
    resolver = DataSourceResolver(store_factory=lambda: _FakeStore(rows=[]))
    res = resolver.resolve("news_rss", {})
    assert res.success is False
    assert res.error == "no_results"


def test_query_failure_retries_with_safe_sentinel():
    store = _FakeStore(rows=[_Row(content="x")], raise_first=True)
    resolver = DataSourceResolver(store_factory=lambda: store)
    res = resolver.resolve("news_rss", {"query": "*"})
    assert res.success
    # First call raised; second call used "a" as the safe sentinel.
    assert len(store.calls) == 2
    assert store.calls[1]["query"] == "a"


def test_store_unavailable_returns_error():
    resolver = DataSourceResolver(store_factory=lambda: None)
    res = resolver.resolve("news_rss", {})
    assert res.success is False
    assert res.error == "store_unavailable"
