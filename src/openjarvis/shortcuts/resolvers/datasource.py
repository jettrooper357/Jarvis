"""Datasource resolver — queries the shared :class:`KnowledgeStore`.

A rule with ``target_kind = "datasource"`` resolves to a search over the
chunks the named connector has synced into the knowledge store. Args:

- ``query`` (str, optional)     — full-text query. Defaults to ``"*"``.
- ``top_k`` (int, optional)     — max rows returned. Default 8.
- ``doc_type`` (str, optional)  — filter on the chunk's ``doc_type``.
- ``since`` (ISO datetime str)  — only chunks newer than this.

When the connector advertises a ``default_post_prompt`` via its
``mcp_tools()`` spec metadata, the resolver bubbles that up so the
post-processor has a sensible per-source default.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from openjarvis.shortcuts._stubs import RawResult, Resolver

_logger = logging.getLogger("openjarvis.shortcuts.resolvers.datasource")


def _format_results(target_id: str, rows: list) -> str:
    if not rows:
        return f"No '{target_id}' results."
    lines = [f"Top results from {target_id}:"]
    for idx, row in enumerate(rows, 1):
        content = (getattr(row, "content", None) or "").strip()
        meta = getattr(row, "metadata", {}) or {}
        title = str(meta.get("title") or meta.get("url") or "Untitled")
        published = str(meta.get("timestamp") or meta.get("published") or "")
        lines.append(f"{idx}. {title}")
        if published:
            lines.append(f"   {published}")
        if content:
            snippet = content[:280].replace("\n", " ").strip()
            lines.append(f"   {snippet}")
    return "\n".join(lines)


class DataSourceResolver(Resolver):
    kind = "datasource"

    def __init__(self, store_factory: Any = None) -> None:
        # Factory injection makes tests independent of the user config dir.
        self._store_factory = store_factory

    def _open_store(self):
        if self._store_factory is not None:
            return self._store_factory()
        try:
            from openjarvis.connectors.store import KnowledgeStore

            return KnowledgeStore()
        except Exception as exc:
            _logger.warning("KnowledgeStore open failed: %s", exc)
            return None

    def _default_post_prompt_for(self, target_id: str) -> Optional[str]:
        try:
            from openjarvis.core.registry import ConnectorRegistry

            cls = ConnectorRegistry.get(target_id)
            instance = cls()
            for spec in instance.mcp_tools() or []:
                metadata = getattr(spec, "metadata", {}) or {}
                prompt = metadata.get("default_post_prompt")
                if prompt:
                    return str(prompt)
        except Exception:
            return None
        return None

    def resolve(self, target_id: str, args: Dict[str, Any]) -> RawResult:
        default_post_prompt = self._default_post_prompt_for(target_id)
        store = self._open_store()
        if store is None:
            return RawResult(
                content="Knowledge store unavailable",
                success=False,
                error="store_unavailable",
                default_post_prompt=default_post_prompt,
            )

        query = str(args.get("query") or args.get("topic") or "*").strip() or "*"
        top_k = int(args.get("top_k") or 8)

        retrieve_kwargs: Dict[str, Any] = {"top_k": top_k, "source": target_id}
        if args.get("doc_type"):
            retrieve_kwargs["doc_type"] = str(args["doc_type"])
        if args.get("since"):
            retrieve_kwargs["since"] = args["since"]

        try:
            try:
                rows = store.retrieve(query, **retrieve_kwargs)
            except Exception:
                # FTS may reject the literal "*" or punctuation-only queries;
                # retry with a safe sentinel.
                rows = store.retrieve("a", **retrieve_kwargs)
        except Exception as exc:
            return RawResult(
                content=f"Knowledge store query failed: {exc}",
                success=False,
                error="store_query_error",
                default_post_prompt=default_post_prompt,
            )
        finally:
            try:
                close = getattr(store, "close", None)
                if callable(close):
                    close()
            except Exception:
                pass

        rows = list(rows or [])
        if not rows:
            return RawResult(
                content=(
                    f"No content from data source '{target_id}'. Sync the "
                    "connector or broaden the query, then ask again."
                ),
                success=False,
                error="no_results",
                metadata={"target_id": target_id, "query": query},
                default_post_prompt=default_post_prompt,
            )

        return RawResult(
            content=_format_results(target_id, rows),
            success=True,
            metadata={
                "target_id": target_id,
                "query": query,
                "num_results": len(rows),
            },
            default_post_prompt=default_post_prompt,
        )


__all__ = ["DataSourceResolver"]
