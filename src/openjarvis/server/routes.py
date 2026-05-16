"""Route handlers for the OpenAI-compatible API server."""

from __future__ import annotations

import logging
import re
import uuid
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from openjarvis.core.types import Message, Role
from openjarvis.server.models import (
    ChatCompletionChunk,
    ChatCompletionRequest,
    ChatCompletionResponse,
    Choice,
    ChoiceMessage,
    ComplexityInfo,
    DeltaMessage,
    ModelListResponse,
    ModelObject,
    StreamChoice,
    UsageInfo,
)

router = APIRouter()


def _to_messages(chat_messages) -> list[Message]:
    """Convert Pydantic ChatMessage objects to core Message objects."""
    messages = []
    for m in chat_messages:
        role = Role(m.role) if m.role in {r.value for r in Role} else Role.USER
        messages.append(
            Message(
                role=role,
                content=m.content or "",
                name=m.name,
                tool_call_id=m.tool_call_id,
            )
        )
    return messages


def _count_tokens(text: str) -> int:
    """Cheap token estimate used for prompt-side context budgeting."""
    return len(text.split())


def _looks_like_news_query(query: str) -> bool:
    q = query.casefold()
    return any(
        term in q
        for term in (
            " news",
            "news ",
            "headline",
            "headlines",
            "current events",
            "rss",
            "feed",
            "feeds",
            "hacker news",
            "hn ",
        )
    ) or q == "news"


_CONNECTOR_STOP_WORDS = {
    "a",
    "an",
    "and",
    "are",
    "for",
    "from",
    "give",
    "headline",
    "headlines",
    "how",
    "i",
    "latest",
    "me",
    "news",
    "of",
    "on",
    "recent",
    "rss",
    "show",
    "tell",
    "the",
    "to",
    "what",
    "with",
}


def _connector_query_candidates(query: str) -> list[str]:
    cleaned = re.sub(r"[^a-zA-Z0-9\s]+", " ", query.casefold())
    tokens = [token for token in cleaned.split() if token and token not in _CONNECTOR_STOP_WORDS]
    candidates: list[str] = []
    if tokens:
        focused = " ".join(tokens)
        if focused not in candidates:
            candidates.append(focused)
    broad = re.sub(r"\s+", " ", cleaned).strip()
    if broad and broad not in candidates:
        candidates.append(broad)
    return candidates or [query.strip()]


def _recent_connector_results(store: Any, *, max_results: int = 5) -> list[Any]:
    rows = store._conn.execute(
        """
        SELECT content, source, metadata
        FROM knowledge_chunks
        WHERE source IN ('news_rss', 'hackernews')
        ORDER BY
            CASE WHEN timestamp != '' THEN timestamp END DESC,
            created_at DESC
        LIMIT ?
        """,
        (max_results,),
    ).fetchall()
    from openjarvis.tools.storage._stubs import RetrievalResult
    import json

    results = []
    for row in rows:
        metadata = json.loads(row["metadata"]) if row["metadata"] else {}
        results.append(
            RetrievalResult(
                content=row["content"],
                score=0.0,
                source=row["source"],
                metadata=metadata,
            )
        )
    return results


def _inject_connector_knowledge_context(
    query: str,
    messages: list[Message],
    *,
    max_results: int = 5,
    max_context_tokens: int = 1200,
) -> list[Message]:
    """Prepend synced connector knowledge from ``knowledge.db`` when available."""
    from pathlib import Path

    from openjarvis.connectors.store import KnowledgeStore
    from openjarvis.core.config import DEFAULT_CONFIG_DIR
    from openjarvis.core.types import Role
    from openjarvis.tools.storage._stubs import RetrievalResult

    knowledge_db = DEFAULT_CONFIG_DIR / "knowledge.db"
    if not Path(knowledge_db).exists():
        return messages

    results: list[RetrievalResult] = []
    try:
        with KnowledgeStore(str(knowledge_db)) as store:
            search_queries = _connector_query_candidates(query)
            if _looks_like_news_query(query):
                for search_query in search_queries:
                    for source in ("news_rss", "hackernews"):
                        results.extend(
                            store.retrieve(
                                search_query,
                                top_k=max(2, max_results // 2),
                                source=source,
                            )
                        )
                    if results:
                        break
            if not results:
                for search_query in search_queries:
                    results = store.retrieve(search_query, top_k=max_results)
                    if results:
                        break
            if not results and _looks_like_news_query(query):
                results = _recent_connector_results(store, max_results=max_results)
    except Exception:
        logging.getLogger("openjarvis.server").debug(
            "Connector knowledge lookup failed",
            exc_info=True,
        )
        return messages

    if not results:
        return messages

    seen: set[str] = set()
    chosen: list[RetrievalResult] = []
    total_tokens = 0
    for result in sorted(results, key=lambda r: getattr(r, "score", 0.0), reverse=True):
        meta = getattr(result, "metadata", {}) or {}
        dedupe_key = str(
            meta.get("chunk_id")
            or meta.get("doc_id")
            or f"{result.source}:{meta.get('title', '')}:{result.content[:120]}"
        )
        if dedupe_key in seen:
            continue
        token_count = _count_tokens(result.content)
        if chosen and total_tokens + token_count > max_context_tokens:
            break
        chosen.append(result)
        seen.add(dedupe_key)
        total_tokens += token_count
        if len(chosen) >= max_results:
            break

    if not chosen:
        return messages

    context_lines = []
    for idx, result in enumerate(chosen, start=1):
        meta = getattr(result, "metadata", {}) or {}
        title = str(meta.get("title", "") or "").strip()
        url = str(meta.get("url", "") or "").strip()
        source = result.source or str(meta.get("source", "") or "").strip()
        label_parts = [part for part in (source, title, url) if part]
        label = " | ".join(label_parts) if label_parts else f"result {idx}"
        context_lines.append(f"{idx}. [{label}] {result.content}")

    context_message = Message(
        role=Role.SYSTEM,
        content=(
            "The following recent context was retrieved from synced connector data. "
            "Use it directly when answering questions about latest news or synced feeds. "
            "If the retrieved items do not actually cover the requested topic, say that clearly "
            "and summarize only what is present in the synced feeds.\n\n"
            + "\n\n".join(context_lines)
        ),
    )
    return [context_message] + list(messages)


@router.post("/v1/chat/completions")
async def chat_completions(request_body: ChatCompletionRequest, request: Request):
    """Handle chat completion requests (streaming and non-streaming)."""
    engine = request.app.state.engine
    agent = getattr(request.app.state, "agent", None)
    # Fall back to the server's configured default when the client omits or
    # sends an empty `model`. The websocket handler does the same; without
    # this, Ollama replies `400: model is required` and the chat UI errors
    # out on first message when nothing has been selected in the sidebar.
    model = request_body.model or getattr(request.app.state, "model", "") or ""
    if not model:
        raise HTTPException(
            status_code=400,
            detail=(
                "No model specified in request and no default configured on "
                "the server. Pass `model` in the request body or start the "
                "server with --model."
            ),
        )

    query_text = ""
    for m in reversed(request_body.messages):
        if m.role == "user" and m.content:
            query_text = m.content
            break

    # Inject memory context into messages before dispatching
    config = getattr(request.app.state, "config", None)
    memory_backend = getattr(request.app.state, "memory_backend", None)
    if (
        config is not None
        and memory_backend is not None
        and config.agent.context_from_memory
        and query_text
    ):
        try:
            from openjarvis.tools.storage.context import ContextConfig, inject_context

            messages = _to_messages(request_body.messages)
            ctx_cfg = ContextConfig(
                top_k=config.memory.context_top_k,
                min_score=config.memory.context_min_score,
                max_context_tokens=config.memory.context_max_tokens,
            )
            enriched = inject_context(
                query_text,
                messages,
                memory_backend,
                config=ctx_cfg,
            )
            # Rebuild request messages from enriched Message objects
            if len(enriched) > len(messages):
                from openjarvis.server.models import ChatMessage

                request_body.messages = [
                    ChatMessage(
                        role=msg.role.value,
                        content=msg.content,
                        name=msg.name,
                        tool_call_id=getattr(msg, "tool_call_id", None),
                    )
                    for msg in enriched
                ]
        except Exception:
            logging.getLogger("openjarvis.server").debug(
                "Memory context injection failed",
                exc_info=True,
            )

    if query_text:
        try:
            from openjarvis.server.models import ChatMessage

            enriched = _inject_connector_knowledge_context(
                query_text,
                _to_messages(request_body.messages),
            )
            if len(enriched) > len(request_body.messages):
                request_body.messages = [
                    ChatMessage(
                        role=msg.role.value,
                        content=msg.content,
                        name=msg.name,
                        tool_call_id=getattr(msg, "tool_call_id", None),
                    )
                    for msg in enriched
                ]
        except Exception:
            logging.getLogger("openjarvis.server").debug(
                "Connector knowledge injection failed",
                exc_info=True,
            )

    # Run complexity analysis on the last user message
    complexity_info = None
    if query_text:
        try:
            from openjarvis.learning.routing.complexity import (
                adjust_tokens_for_model,
                score_complexity,
            )

            cr = score_complexity(query_text)
            suggested = adjust_tokens_for_model(
                cr.suggested_max_tokens,
                model,
            )
            complexity_info = ComplexityInfo(
                score=cr.score,
                tier=cr.tier,
                suggested_max_tokens=suggested,
            )
            # Bump max_tokens when complexity suggests more than what
            # the client requested — never reduce below the request value.
            if suggested > request_body.max_tokens:
                request_body.max_tokens = suggested
        except Exception:
            logging.getLogger("openjarvis.server").debug(
                "Complexity analysis failed",
                exc_info=True,
            )

    if request_body.stream:
        bus = getattr(request.app.state, "bus", None)
        # Route streaming chat through the agent whenever one is available so
        # the chat box can use the agent's tools (web_search, etc.) and answer
        # with live data. Tradeoff: the bridge runs agent.run() synchronously
        # and word-splits the result, so turns are not streamed token-by-token
        # in real time. Fall back to direct engine streaming only when no
        # agent/bus exists.
        if agent is not None and bus is not None:
            return await _handle_agent_stream(agent, bus, model, request_body)
        return await _handle_stream(engine, model, request_body, complexity_info)

    # Non-streaming: use agent if available, otherwise direct engine call
    if agent is not None:
        return _handle_agent(agent, model, request_body, complexity_info)

    bus = getattr(request.app.state, "bus", None)
    return _handle_direct(
        engine,
        model,
        request_body,
        bus=bus,
        complexity_info=complexity_info,
    )


def _handle_direct(
    engine,
    model: str,
    req: ChatCompletionRequest,
    bus=None,
    complexity_info=None,
) -> ChatCompletionResponse:
    """Direct engine call without agent."""
    messages = _to_messages(req.messages)
    kwargs: dict[str, Any] = {}
    if req.tools:
        kwargs["tools"] = req.tools
    if bus:
        from openjarvis.telemetry.wrapper import instrumented_generate

        result = instrumented_generate(
            engine,
            messages,
            model=model,
            bus=bus,
            temperature=req.temperature,
            max_tokens=req.max_tokens,
            **kwargs,
        )
    else:
        result = engine.generate(
            messages,
            model=model,
            temperature=req.temperature,
            max_tokens=req.max_tokens,
            **kwargs,
        )
    content = result.get("content", "")
    usage = result.get("usage", {})

    choice_msg = ChoiceMessage(role="assistant", content=content)
    # Include tool calls if present
    tool_calls = result.get("tool_calls")
    if tool_calls:
        choice_msg.tool_calls = [
            {
                "id": tc.get("id", ""),
                "type": "function",
                "function": {
                    "name": tc.get("name", ""),
                    "arguments": tc.get("arguments", "{}"),
                },
            }
            for tc in tool_calls
        ]

    return ChatCompletionResponse(
        model=model,
        choices=[
            Choice(
                message=choice_msg,
                finish_reason=result.get("finish_reason", "stop"),
            )
        ],
        usage=UsageInfo(
            prompt_tokens=usage.get("prompt_tokens", 0),
            completion_tokens=usage.get("completion_tokens", 0),
            total_tokens=usage.get("total_tokens", 0),
        ),
        complexity=complexity_info,
    )


def _handle_agent(
    agent,
    model: str,
    req: ChatCompletionRequest,
    complexity_info=None,
) -> ChatCompletionResponse:
    """Run through agent."""
    from openjarvis.agents._stubs import AgentContext

    # Build context from prior messages
    ctx = AgentContext()
    if len(req.messages) > 1:
        prior = _to_messages(req.messages[:-1])
        for m in prior:
            ctx.conversation.add(m)

    # Last message is the input
    input_text = req.messages[-1].content if req.messages else ""

    # Override agent model for this request if the caller specified one
    original_model = agent._model
    if model:
        agent._model = model
    try:
        result = agent.run(input_text, context=ctx)
    finally:
        agent._model = original_model

    usage = UsageInfo(
        prompt_tokens=result.metadata.get("prompt_tokens", 0),
        completion_tokens=result.metadata.get("completion_tokens", 0),
        total_tokens=result.metadata.get("total_tokens", 0),
    )

    # Include audio metadata if the agent produced audio (e.g. morning digest)
    audio_meta = None
    audio_path = result.metadata.get("audio_path", "")
    if audio_path:
        from pathlib import Path

        from openjarvis.server.models import AudioMeta

        if Path(audio_path).exists():
            audio_meta = AudioMeta(url="/api/digest/audio")

    return ChatCompletionResponse(
        model=model,
        choices=[
            Choice(
                message=ChoiceMessage(
                    role="assistant",
                    content=result.content,
                    audio=audio_meta,
                ),
                finish_reason="stop",
            )
        ],
        usage=usage,
        complexity=complexity_info,
    )


async def _handle_agent_stream(agent, bus, model, req):
    """Stream agent response with EventBus events via SSE."""
    from openjarvis.server.stream_bridge import create_agent_stream

    return await create_agent_stream(agent, bus, model, req)


async def _handle_stream(
    engine,
    model: str,
    req: ChatCompletionRequest,
    complexity_info=None,
):
    """Stream response using SSE format."""
    from openjarvis.server.cloud_router import (
        is_cloud_model,
        stream_cloud,
        stream_local,
    )

    messages = _to_messages(req.messages)
    chunk_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"

    # Route directly to the right backend — bypasses engine routing entirely
    # so broken MultiEngine state can never misdirect requests.
    use_cloud = is_cloud_model(model)

    async def generate():
        # Send role chunk first
        first_chunk = ChatCompletionChunk(
            id=chunk_id,
            model=model,
            choices=[
                StreamChoice(
                    delta=DeltaMessage(role="assistant"),
                )
            ],
        )
        yield f"data: {first_chunk.model_dump_json()}\n\n"

        try:
            # Cloud models → direct cloud API (reads keys from disk).
            # Local models → engine.stream() first so mock engines work in
            # tests.  Fall back to stream_local() only when the engine would
            # mis-route the request to a cloud backend (MultiEngine routing
            # confusion), which is detected by checking the routed engine's
            # is_cloud attribute.
            if use_cloud:
                token_iter = stream_cloud(
                    model, messages, req.temperature, req.max_tokens
                )
            else:
                # Use engine.stream() by default (preserves mock-engine
                # compatibility in tests).  Only fall back to stream_local()
                # when a real MultiEngine would mis-route the local model to a
                # cloud backend — detected via isinstance so mocks are not
                # accidentally matched.
                _use_local_fallback = False
                try:
                    from openjarvis.engine.multi import MultiEngine

                    _inner = getattr(engine, "_inner", engine)
                    if isinstance(_inner, MultiEngine):
                        _routed = _inner._engine_for(model)
                        if _routed is not None and getattr(_routed, "is_cloud", False):
                            _use_local_fallback = True
                except Exception:
                    pass
                if _use_local_fallback:
                    token_iter = stream_local(
                        model, messages, req.temperature, req.max_tokens
                    )
                else:
                    token_iter = engine.stream(
                        messages,
                        model=model,
                        temperature=req.temperature,
                        max_tokens=req.max_tokens,
                    )
            async for token in token_iter:
                chunk = ChatCompletionChunk(
                    id=chunk_id,
                    model=model,
                    choices=[
                        StreamChoice(
                            delta=DeltaMessage(content=token),
                        )
                    ],
                )
                yield f"data: {chunk.model_dump_json()}\n\n"
        except Exception as exc:
            # Surface errors as a content chunk so the frontend can
            # display them instead of silently failing.
            import logging

            logging.getLogger("openjarvis.server").error(
                "Stream error: %s",
                exc,
                exc_info=True,
            )
            error_chunk = ChatCompletionChunk(
                id=chunk_id,
                model=model,
                choices=[
                    StreamChoice(
                        delta=DeltaMessage(
                            content=f"\n\nError during generation: {exc}",
                        ),
                        finish_reason="stop",
                    )
                ],
            )
            yield f"data: {error_chunk.model_dump_json()}\n\n"
            yield "data: [DONE]\n\n"
            return

        # Send finish chunk with usage data if available
        import json as _json

        finish_data = ChatCompletionChunk(
            id=chunk_id,
            model=model,
            choices=[
                StreamChoice(
                    delta=DeltaMessage(),
                    finish_reason="stop",
                )
            ],
        )
        finish_dict = _json.loads(finish_data.model_dump_json())

        # Tag the finish chunk with the correct engine label.
        # We use the routing decision (use_cloud) directly rather than
        # unwrapping the engine chain, which can be in a broken state.
        finish_dict.setdefault("telemetry", {})
        finish_dict["telemetry"]["engine"] = "cloud" if use_cloud else "ollama"

        if complexity_info is not None:
            finish_dict["complexity"] = complexity_info.model_dump()

        yield f"data: {_json.dumps(finish_dict)}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


@router.get("/v1/models")
async def list_models(request: Request) -> ModelListResponse:
    """List locally installed models (Ollama).

    Cloud models are not included here — they live in the Cloud Models tab
    of the UI and are selected there, not from this endpoint.
    """
    from openjarvis.server.cloud_router import is_cloud_model, list_local_models

    # Prefer engine.list_models() so mock engines work in tests.
    # Filter out any cloud model IDs that may appear via MultiEngine.
    # Fall back to direct Ollama query only when the engine returns nothing.
    engine = request.app.state.engine
    all_ids = engine.list_models()
    model_ids = [m for m in all_ids if not is_cloud_model(m)]
    if not model_ids:
        model_ids = await list_local_models()

    return ModelListResponse(
        data=[ModelObject(id=mid) for mid in model_ids],
    )


@router.post("/v1/models/pull")
async def pull_model(request: Request):
    """Pull / download a model from the Ollama registry."""
    body = await request.json()
    model_name = body.get("model", "").strip()
    if not model_name:
        raise HTTPException(status_code=400, detail="'model' field is required")

    engine = request.app.state.engine
    engine_name = getattr(request.app.state, "engine_name", "")
    # Only Ollama supports pulling
    if engine_name != "ollama" and getattr(engine, "engine_id", "") != "ollama":
        raise HTTPException(
            status_code=501,
            detail="Model pulling is only supported with the Ollama engine",
        )

    import httpx as _httpx

    host = getattr(engine, "_host", "http://localhost:11434")
    client = _httpx.Client(base_url=host, timeout=600.0)
    try:
        resp = client.post(
            "/api/pull",
            json={"name": model_name, "stream": False},
        )
        resp.raise_for_status()
    except (_httpx.ConnectError, _httpx.TimeoutException) as exc:
        raise HTTPException(status_code=502, detail=f"Ollama unreachable: {exc}")
    except _httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=exc.response.status_code,
            detail=f"Ollama error: {exc.response.text[:300]}",
        )
    finally:
        client.close()

    return {"status": "ok", "model": model_name}


@router.delete("/v1/models/{model_name:path}")
async def delete_model(model_name: str, request: Request):
    """Delete a model from Ollama."""
    engine = request.app.state.engine
    engine_name = getattr(request.app.state, "engine_name", "")
    if engine_name != "ollama" and getattr(engine, "engine_id", "") != "ollama":
        raise HTTPException(status_code=501, detail="Only supported with Ollama engine")

    import httpx as _httpx

    host = getattr(engine, "_host", "http://localhost:11434")
    client = _httpx.Client(base_url=host, timeout=30.0)
    try:
        resp = client.request(
            "DELETE",
            "/api/delete",
            json={"name": model_name},
        )
        resp.raise_for_status()
    except (_httpx.ConnectError, _httpx.TimeoutException) as exc:
        raise HTTPException(status_code=502, detail=f"Ollama unreachable: {exc}")
    except _httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=exc.response.status_code,
            detail=f"Ollama error: {exc.response.text[:300]}",
        )
    finally:
        client.close()

    return {"status": "deleted", "model": model_name}


@router.post("/v1/cloud/reload")
async def reload_cloud_engine(request: Request):
    """Hot-reload cloud API keys and (re-)initialize the cloud engine.

    Called by the desktop app immediately after the user saves a cloud API
    key so that cloud models become available without a full app restart.
    """
    import os
    from pathlib import Path

    # Re-read ~/.openjarvis/cloud-keys.env and update the running process env.
    keys_path = Path.home() / ".openjarvis" / "cloud-keys.env"
    if keys_path.exists():
        for raw_line in keys_path.read_text().splitlines():
            line = raw_line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ[k.strip()] = v.strip()

    # Try to build a fresh CloudEngine.
    try:
        from openjarvis.engine.cloud import CloudEngine
        from openjarvis.engine.multi import MultiEngine

        cloud = CloudEngine()
        if not cloud.health():
            return {
                "status": "no_cloud",
                "message": "No cloud models available (check API keys)",
            }
    except Exception as exc:
        return {"status": "error", "message": str(exc)}

    # Locate the innermost engine, working through InstrumentedEngine layers.
    outer = request.app.state.engine
    inner = getattr(outer, "_inner", outer)

    if isinstance(inner, MultiEngine):
        # Replace or insert the cloud entry in the existing MultiEngine.
        new_engines = [(k, e) for k, e in inner._engines if k != "cloud"]
        new_engines.append(("cloud", cloud))
        inner._engines = new_engines
        inner._refresh_map()
    else:
        # Wrap the existing engine (which may be security-wrapped) with a new
        # MultiEngine that includes the cloud engine.
        engine_name = getattr(request.app.state, "engine_name", "local")
        new_multi = MultiEngine([(engine_name, inner), ("cloud", cloud)])
        if hasattr(outer, "_inner"):
            outer._inner = new_multi
        else:
            request.app.state.engine = new_multi
        request.app.state.engine_name = "multi"

    return {"status": "ok", "message": "Cloud engine reloaded"}


@router.get("/v1/savings")
async def savings(request: Request):
    """Return savings summary compared to cloud providers.

    Only includes telemetry from the current server session so that
    counters start at zero each time a new model + agent is launched.
    """
    from openjarvis.core.config import DEFAULT_CONFIG_DIR
    from openjarvis.server.savings import compute_savings, savings_to_dict
    from openjarvis.telemetry.aggregator import TelemetryAggregator

    db_path = DEFAULT_CONFIG_DIR / "telemetry.db"
    if not db_path.exists():
        empty = compute_savings(0, 0, 0)
        return savings_to_dict(empty)

    session_start = getattr(request.app.state, "session_start", None)

    agg = TelemetryAggregator(db_path)
    try:
        summary = agg.summary(since=session_start)
        # Exclude cloud model tokens from savings — only local
        # inference counts toward cost savings.
        _cloud_prefixes = (
            "gpt-",
            "o1-",
            "o3-",
            "o4-",
            "claude-",
            "gemini-",
            "openrouter/",
        )
        local_models = [
            m
            for m in summary.per_model
            if not any(m.model_id.startswith(p) for p in _cloud_prefixes)
        ]
        result = compute_savings(
            prompt_tokens=sum(m.prompt_tokens for m in local_models),
            completion_tokens=sum(m.completion_tokens for m in local_models),
            total_calls=sum(m.call_count for m in local_models),
            session_start=session_start if session_start else 0.0,
            prompt_tokens_evaluated=sum(
                m.prompt_tokens_evaluated for m in local_models
            ),
        )
        return savings_to_dict(result)
    finally:
        agg.close()


@router.post("/v1/telemetry/reset")
async def reset_telemetry():
    """Clear all stored telemetry records.

    Useful after updating token-counting methodology — clears
    historical records that were computed under the old rules so
    that the savings dashboard and leaderboard submissions start
    fresh with corrected values.
    """
    from openjarvis.core.config import DEFAULT_CONFIG_DIR
    from openjarvis.telemetry.aggregator import TelemetryAggregator

    db_path = DEFAULT_CONFIG_DIR / "telemetry.db"
    if not db_path.exists():
        return {"status": "ok", "records_cleared": 0}

    agg = TelemetryAggregator(db_path)
    try:
        count = agg.clear()
    finally:
        agg.close()
    return {"status": "ok", "records_cleared": count}


@router.get("/v1/info")
async def server_info(request: Request):
    """Return server configuration: model, agent, engine."""
    agent = getattr(request.app.state, "agent", None)
    agent_id = getattr(agent, "agent_id", None) if agent else None
    # Fall back to configured agent name if agent didn't instantiate
    if agent_id is None:
        agent_id = getattr(request.app.state, "agent_name", None)
    return {
        "model": getattr(request.app.state, "model", ""),
        "agent": agent_id,
        "engine": getattr(request.app.state, "engine_name", ""),
    }


@router.get("/health")
async def health(request: Request):
    """Health check endpoint."""
    engine = request.app.state.engine
    healthy = engine.health()
    if not healthy:
        raise HTTPException(status_code=503, detail="Engine unhealthy")
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Channel endpoints
# ---------------------------------------------------------------------------


@router.get("/v1/channels")
async def list_channels(request: Request):
    """List available messaging channels."""
    bridge = getattr(request.app.state, "channel_bridge", None)
    if bridge is None:
        return {"channels": [], "message": "Channel bridge not configured"}
    channels = bridge.list_channels()
    return {"channels": channels, "status": bridge.status().value}


@router.post("/v1/channels/send")
async def channel_send(request: Request):
    """Send a message to a channel."""
    bridge = getattr(request.app.state, "channel_bridge", None)
    if bridge is None:
        raise HTTPException(status_code=503, detail="Channel bridge not configured")

    body = await request.json()
    channel_name = body.get("channel", "")
    content = body.get("content", "")
    conversation_id = body.get("conversation_id", "")

    if not channel_name or not content:
        raise HTTPException(
            status_code=400,
            detail="'channel' and 'content' are required",
        )

    ok = bridge.send(channel_name, content, conversation_id=conversation_id)
    if not ok:
        raise HTTPException(status_code=502, detail="Failed to send message")
    return {"status": "sent", "channel": channel_name}


@router.get("/v1/channels/status")
async def channel_status(request: Request):
    """Return channel bridge connection status."""
    bridge = getattr(request.app.state, "channel_bridge", None)
    if bridge is None:
        return {"status": "not_configured"}
    return {"status": bridge.status().value}


@router.get("/v1/channels/telegram/config")
async def telegram_config_get():
    """Return the saved Telegram bot config for the local UI."""
    from openjarvis.channels.telegram import (
        _load_allowed_chats_from_credentials_file,
        _load_token_from_credentials_file,
    )

    token = _load_token_from_credentials_file()
    return {
        "has_token": bool(token),
        "token_preview": f"{token[:6]}…{token[-4:]}" if token else "",
        "bot_token": token or "",
        "allowed_chat_ids": _load_allowed_chats_from_credentials_file(),
    }


@router.get("/v1/channels/telegram/health")
async def telegram_health():
    """Check whether the backend can reach the Telegram Bot API."""
    from openjarvis.channels.telegram import _load_token_from_credentials_file

    token = _load_token_from_credentials_file().strip()
    if not token:
        return {
            "configured": False,
            "status": "not_configured",
            "message": "No Telegram bot token is saved yet.",
        }

    try:
        response = httpx.get(
            f"https://api.telegram.org/bot{token}/getMe",
            timeout=8.0,
        )
    except httpx.RequestError as exc:
        return {
            "configured": True,
            "status": "network_error",
            "message": (
                "The backend cannot reach api.telegram.org. "
                "Telegram may be blocked by your VPN, firewall, proxy, or DNS."
            ),
            "detail": str(exc),
        }

    try:
        payload = response.json()
    except ValueError:
        payload = {}

    if response.status_code == 401:
        return {
            "configured": True,
            "status": "invalid_token",
            "message": "Telegram rejected the saved bot token.",
            "detail": str(payload.get("description") or response.text or "Unauthorized"),
        }

    if response.status_code >= 300:
        return {
            "configured": True,
            "status": "telegram_error",
            "message": "Telegram returned an error while validating the bot token.",
            "detail": str(
                payload.get("description")
                or response.text
                or f"HTTP {response.status_code}"
            ),
        }

    if not payload.get("ok", False):
        return {
            "configured": True,
            "status": "telegram_error",
            "message": "Telegram did not confirm the bot connection.",
            "detail": str(payload.get("description") or "Unknown Telegram error"),
        }

    result = payload.get("result") or {}
    return {
        "configured": True,
        "status": "ok",
        "message": "Telegram Bot API is reachable from this backend.",
        "bot_username": result.get("username", ""),
        "bot_id": result.get("id"),
    }


@router.post("/v1/channels/telegram/config")
async def telegram_config_set(request: Request):
    """Persist the Telegram bot_token (and optional allowed_chat_ids).

    Writes to ``~/.openjarvis/connectors/telegram.json`` (mode 0o600). New
    ``TelegramChannel`` instances will pick it up on next backend start; the
    response surfaces a ``restart_required`` flag the UI can show.
    """
    from openjarvis.channels.telegram import save_credentials

    body = await request.json()
    bot_token = (body.get("bot_token") or "").strip()
    allowed_chat_ids = (body.get("allowed_chat_ids") or "").strip()
    if not bot_token:
        raise HTTPException(status_code=400, detail="bot_token is required")

    save_credentials(bot_token, allowed_chat_ids)
    return {
        "saved": True,
        "token_preview": f"{bot_token[:6]}…{bot_token[-4:]}",
        "bot_token": bot_token,
        "allowed_chat_ids": allowed_chat_ids,
        "restart_required": True,
    }


# ---------------------------------------------------------------------------
# Security scan endpoint
# ---------------------------------------------------------------------------


@router.get("/v1/security/scan")
async def security_scan():
    """Run a read-only security environment audit and return findings."""
    from openjarvis.cli.scan_cmd import PrivacyScanner

    scanner = PrivacyScanner()
    results = scanner.run_all()
    return {
        "has_warnings": any(r.status == "warn" for r in results),
        "has_failures": any(r.status == "fail" for r in results),
        "findings": [
            {
                "name": r.name,
                "status": r.status,
                "message": r.message,
                "platform": r.platform,
            }
            for r in results
        ],
    }


__all__ = ["router"]
