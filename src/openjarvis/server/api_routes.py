"""Extended API routes for agents, workflows, memory, traces, etc."""

from __future__ import annotations

import inspect
import json
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

logger = logging.getLogger(__name__)

# ---- Request/Response models ----


class AgentCreateRequest(BaseModel):
    agent_type: str
    tools: Optional[List[str]] = None
    agent_id: Optional[str] = None


class AgentMessageRequest(BaseModel):
    message: str


class MemoryStoreRequest(BaseModel):
    content: str
    metadata: Optional[Dict[str, Any]] = None


class MemorySearchRequest(BaseModel):
    query: str
    top_k: int = 5


class MemoryIndexRequest(BaseModel):
    path: str


class BudgetLimitsRequest(BaseModel):
    max_tokens_per_day: Optional[int] = None
    max_requests_per_hour: Optional[int] = None


class FeedbackScoreRequest(BaseModel):
    trace_id: str
    score: float
    source: str = "api"


class OptimizeRunRequest(BaseModel):
    benchmark: str
    max_trials: int = 20
    optimizer_model: str = "claude-sonnet-4-6"
    max_samples: int = 50


class SkillDocumentRequest(BaseModel):
    content: str


class SkillInstallRequest(BaseModel):
    """Install a skill from a remote source (mirrors ``jarvis skill install``)."""

    source: str
    name: str = ""
    url: str = ""
    with_scripts: bool = False
    force: bool = False


# ---- Agent routes ----

agents_router = APIRouter(prefix="/v1/agents", tags=["agents"])


@agents_router.get("")
async def list_agents(request: Request):
    """List available agent types and running agents."""
    registered = []
    try:
        import openjarvis.agents  # noqa: F401 — side-effect registration
        from openjarvis.core.registry import AgentRegistry

        for key in sorted(AgentRegistry.keys()):
            cls = AgentRegistry.get(key)
            registered.append(
                {
                    "key": key,
                    "class": cls.__name__,
                    "accepts_tools": getattr(cls, "accepts_tools", False),
                }
            )
    except Exception as exc:
        logger.warning("Failed to list registered agents: %s", exc)

    running = []
    try:
        from openjarvis.tools.agent_tools import _SPAWNED_AGENTS

        running = [{"id": k, **v} for k, v in _SPAWNED_AGENTS.items()]
    except ImportError:
        pass

    return {"registered": registered, "running": running}


@agents_router.post("")
async def create_agent(req: AgentCreateRequest, request: Request):
    """Spawn a new agent."""
    try:
        from openjarvis.tools.agent_tools import AgentSpawnTool

        tool = AgentSpawnTool()
        params = {"agent_type": req.agent_type}
        if req.tools:
            params["tools"] = ",".join(req.tools)
        if req.agent_id:
            params["agent_id"] = req.agent_id
        result = tool.execute(**params)
        if not result.success:
            raise HTTPException(status_code=400, detail=result.content)
        return {
            "status": "created",
            "content": result.content,
            "metadata": result.metadata,
        }
    except ImportError:
        raise HTTPException(status_code=501, detail="Agent tools not available")


@agents_router.delete("/{agent_id}")
async def kill_agent(agent_id: str, request: Request):
    """Kill a running agent."""
    try:
        from openjarvis.tools.agent_tools import AgentKillTool

        tool = AgentKillTool()
        result = tool.execute(agent_id=agent_id)
        if not result.success:
            raise HTTPException(status_code=404, detail=result.content)
        return {"status": "stopped", "agent_id": agent_id}
    except ImportError:
        raise HTTPException(status_code=501, detail="Agent tools not available")


@agents_router.post("/{agent_id}/message")
async def message_agent(agent_id: str, req: AgentMessageRequest, request: Request):
    """Send a message to a running agent."""
    try:
        from openjarvis.tools.agent_tools import AgentSendTool

        tool = AgentSendTool()
        result = tool.execute(agent_id=agent_id, message=req.message)
        if not result.success:
            raise HTTPException(status_code=404, detail=result.content)
        return {"status": "sent", "content": result.content}
    except ImportError:
        raise HTTPException(status_code=501, detail="Agent tools not available")


# ---- Memory routes ----

memory_router = APIRouter(prefix="/v1/memory", tags=["memory"])


def _get_memory_backend(request: Request):
    """Return the app-level memory backend, falling back to a fresh SQLiteMemory."""
    backend = getattr(request.app.state, "memory_backend", None)
    if backend is None:
        try:
            from openjarvis.tools.storage.sqlite import SQLiteMemory

            backend = SQLiteMemory()
        except Exception:
            return None
    return backend


@memory_router.post("/store")
async def memory_store(req: MemoryStoreRequest, request: Request):
    """Store content in memory."""
    backend = _get_memory_backend(request)
    if backend is None:
        return {"status": "stored", "note": "no backend available"}
    try:
        backend.store(req.content, metadata=req.metadata or {})
        return {"status": "stored"}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@memory_router.post("/search")
async def memory_search(req: MemorySearchRequest, request: Request):
    """Search memory for relevant content."""
    backend = _get_memory_backend(request)
    if backend is None:
        return {"results": []}
    try:
        results = backend.retrieve(req.query, top_k=req.top_k)
        items = [
            {
                "content": r.content,
                "score": getattr(r, "score", 0.0),
                "metadata": getattr(r, "metadata", {}),
            }
            for r in results
        ]
        return {"results": items}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@memory_router.get("/stats")
async def memory_stats(request: Request):
    """Get memory backend statistics."""
    backend = _get_memory_backend(request)
    if backend is None:
        return {"entries": 0, "backend": "none", "status": "not_configured"}
    try:
        return {
            "entries": backend.count(),
            "backend": getattr(backend, "backend_id", "unknown"),
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@memory_router.get("/config")
async def memory_config(request: Request):
    """Return current memory configuration."""
    try:
        config = getattr(request.app.state, "config", None)
        if config is None:
            from openjarvis.core.config import load_config

            config = load_config()
        backend = getattr(request.app.state, "memory_backend", None)
        return {
            "backend_type": (
                backend.backend_id
                if backend is not None
                else config.memory.default_backend
            ),
            "context_top_k": config.memory.context_top_k,
            "context_min_score": config.memory.context_min_score,
            "context_max_tokens": config.memory.context_max_tokens,
            "context_from_memory": config.agent.context_from_memory,
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@memory_router.post("/index")
async def memory_index(req: MemoryIndexRequest, request: Request):
    """Index files from a path into memory."""
    try:
        from pathlib import Path

        from openjarvis.tools.storage.ingest import ingest_path

        target = Path(req.path).expanduser().resolve()
        if not target.exists():
            raise HTTPException(status_code=404, detail=f"Path not found: {req.path}")

        backend = _get_memory_backend(request)
        if backend is None:
            raise HTTPException(status_code=503, detail="No memory backend available")

        chunks = ingest_path(target)
        stored = 0
        for chunk in chunks:
            metadata = {"source": getattr(chunk, "source", str(target))}
            if hasattr(chunk, "metadata") and chunk.metadata:
                metadata.update(chunk.metadata)
            backend.store(chunk.content, metadata=metadata)
            stored += 1

        return {"status": "indexed", "chunks_indexed": stored}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# ---- Traces routes ----

traces_router = APIRouter(prefix="/v1/traces", tags=["traces"])


def _serialise_trace(trace) -> dict:
    """Convert a Trace dataclass to a frontend-friendly dict."""
    import datetime
    from dataclasses import asdict

    d = asdict(trace)
    d["id"] = d.pop("trace_id", "")
    started = d.pop("started_at", 0.0)
    d["created_at"] = (
        datetime.datetime.fromtimestamp(started, tz=datetime.timezone.utc).isoformat()
        if started
        else None
    )
    dur = d.pop("total_latency_seconds", 0.0)
    d["duration_ms"] = round(dur * 1000)
    for step in d.get("steps", []):
        st = step.get("step_type")
        if hasattr(st, "value"):
            step["step_type"] = st.value
    return d


@traces_router.get("")
async def list_traces(request: Request, limit: int = 20):
    """List recent traces."""
    try:
        store = getattr(request.app.state, "trace_store", None)
        if store is None:
            return {"traces": []}
        traces = store.list_traces(limit=limit)
        items = [_serialise_trace(t) for t in traces]
        return {"traces": items}
    except Exception as exc:
        return {"traces": [], "error": str(exc)}


@traces_router.get("/{trace_id}")
async def get_trace(trace_id: str, request: Request):
    """Get a specific trace by ID."""
    try:
        store = getattr(request.app.state, "trace_store", None)
        if store is None:
            raise HTTPException(status_code=404, detail="Trace not found")
        trace = store.get(trace_id)
        if trace is None:
            raise HTTPException(status_code=404, detail="Trace not found")
        return _serialise_trace(trace)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# ---- Telemetry routes ----

telemetry_router = APIRouter(prefix="/v1/telemetry", tags=["telemetry"])


@telemetry_router.get("/stats")
async def telemetry_stats(request: Request):
    """Get aggregated telemetry statistics."""
    try:
        from dataclasses import asdict

        from openjarvis.core.config import DEFAULT_CONFIG_DIR
        from openjarvis.telemetry.aggregator import TelemetryAggregator

        db_path = DEFAULT_CONFIG_DIR / "telemetry.db"
        if not db_path.exists():
            return {"total_requests": 0, "total_tokens": 0}

        session_start = getattr(request.app.state, "session_start", None)
        agg = TelemetryAggregator(db_path)
        try:
            stats = agg.summary(since=session_start)
            d = asdict(stats)
            d.pop("per_model", None)
            d.pop("per_engine", None)
            d["total_requests"] = d.pop("total_calls", 0)
            return d
        finally:
            agg.close()
    except Exception as exc:
        return {"error": str(exc)}


@telemetry_router.get("/energy")
async def telemetry_energy(request: Request):
    """Get energy monitoring data."""
    try:
        from openjarvis.core.config import DEFAULT_CONFIG_DIR
        from openjarvis.telemetry.aggregator import TelemetryAggregator

        db_path = DEFAULT_CONFIG_DIR / "telemetry.db"
        if not db_path.exists():
            return {
                "total_energy_j": 0,
                "energy_per_token_j": 0,
                "avg_power_w": 0,
                "cpu_temp_c": None,
                "gpu_temp_c": None,
            }

        session_start = getattr(request.app.state, "session_start", None)
        agg = TelemetryAggregator(db_path)
        try:
            stats = agg.summary(since=session_start)
            total_energy = stats.total_energy_joules
            total_tokens = stats.total_tokens
            total_latency = stats.total_latency
            return {
                "total_energy_j": total_energy,
                "energy_per_token_j": (
                    total_energy / total_tokens if total_tokens > 0 else 0
                ),
                "avg_power_w": (
                    total_energy / total_latency if total_latency > 0 else 0
                ),
                "cpu_temp_c": None,
                "gpu_temp_c": None,
            }
        finally:
            agg.close()
    except Exception as exc:
        return {"error": str(exc)}


# ---- Skills routes ----

skills_router = APIRouter(prefix="/v1/skills", tags=["skills"])


@skills_router.get("")
async def list_skills(request: Request):
    """List installed skills."""
    try:
        from openjarvis.agents.library import list_skills

        return {"skills": list_skills()}
    except Exception as exc:
        logger.warning("Failed to list skills: %s", exc)
        return {"skills": []}


def _build_skill_resolver(source: str, url: str = ""):
    """Return a source resolver instance (no Click dependency).

    Mirrors ``openjarvis.cli.skill_cmd._get_resolver`` but raises plain
    ``ValueError`` so the HTTP layer can translate to a 400.
    """
    source = (source or "").strip().lower()
    if source == "hermes":
        from openjarvis.skills.sources.hermes import HermesResolver

        return HermesResolver()
    if source == "openclaw":
        from openjarvis.skills.sources.openclaw import OpenClawResolver

        return OpenClawResolver()
    if source == "github":
        if not url:
            raise ValueError("github source requires a repository url")
        from pathlib import Path

        from openjarvis.skills.sources.github import GitHubResolver

        cache = Path(
            "~/.openjarvis/skill-cache/github/" + url.rstrip("/").rsplit("/", 1)[-1]
        ).expanduser()
        return GitHubResolver(cache_root=cache, repo_url=url)
    raise ValueError(
        f"Unknown source {source!r} (expected hermes, openclaw, or github)"
    )


@skills_router.get("/browse")
async def browse_skills(
    source: str,
    query: str = "",
    category: str = "",
    url: str = "",
):
    """Sync a remote source and return matching installable skills.

    The first call to a source clones its repository and can take a while
    (OpenClaw in particular is large).
    """
    try:
        resolver = _build_skill_resolver(source, url)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    try:
        await run_in_threadpool(resolver.sync)
        available = await run_in_threadpool(resolver.list_skills)
    except Exception as exc:
        raise HTTPException(
            status_code=502, detail=f"Failed to sync source: {exc}"
        ) from exc

    q = (query or "").strip().lower()
    cat = (category or "").strip()
    results = []
    for s in available:
        if cat and s.category != cat:
            continue
        haystack = f"{s.name or ''} {s.description or ''} {s.category or ''}".lower()
        if q and q not in haystack:
            continue
        results.append(
            {
                "name": s.name,
                "category": s.category or "",
                "description": s.description or "",
                "source": source,
            }
        )
    results.sort(key=lambda r: (r["category"], r["name"]))
    return {"skills": results[:500], "total": len(results)}


@skills_router.post("/install")
async def install_skill(req: SkillInstallRequest):
    """Install a single skill from a remote source."""
    name = (req.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="A skill name is required")
    try:
        resolver = _build_skill_resolver(req.source, req.url)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    def _do_install():
        resolver.sync()
        if "/" in name:
            category, _, skill_name = name.partition("/")
            matches = [
                s
                for s in resolver.list_skills()
                if s.name == skill_name and s.category == category
            ]
        else:
            matches = [s for s in resolver.list_skills() if s.name == name]
        if not matches:
            raise FileNotFoundError(
                f"No skill named '{name}' found in source '{req.source}'"
            )
        from openjarvis.skills.importer import SkillImporter
        from openjarvis.skills.parser import SkillParser
        from openjarvis.skills.tool_translator import ToolTranslator

        importer = SkillImporter(
            parser=SkillParser(), tool_translator=ToolTranslator()
        )
        return importer.import_skill(
            matches[0], with_scripts=req.with_scripts, force=req.force
        )

    try:
        result = await run_in_threadpool(_do_install)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=502, detail=f"Install failed: {exc}"
        ) from exc

    if not result.success:
        raise HTTPException(
            status_code=400,
            detail="; ".join(result.warnings or ["unknown error"]),
        )
    return {
        "success": True,
        "skipped": result.skipped,
        "name": name,
        "source": req.source,
        "target_path": str(result.target_path) if result.target_path else "",
        "translated_tools": result.translated_tools,
        "untranslated_tools": result.untranslated_tools,
        "scripts_imported": result.scripts_imported,
        "warnings": result.warnings,
    }


@skills_router.post("")
async def save_skill(req: SkillDocumentRequest):
    try:
        from openjarvis.agents.library import save_skill_document

        return save_skill_document(req.content)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@skills_router.get("/{skill_name}")
async def get_skill(skill_name: str):
    try:
        from openjarvis.agents.library import get_skill_document

        return get_skill_document(skill_name)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@skills_router.put("/{skill_name}")
async def update_skill(skill_name: str, req: SkillDocumentRequest):
    try:
        from openjarvis.agents.library import parse_skill_content, save_skill_document

        parsed = parse_skill_content(req.content)
        if str(parsed.get("name", "")) != str(skill_name):
            raise ValueError("Skill name in content must match the URL")
        return save_skill_document(req.content)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@skills_router.delete("/{skill_name}")
async def remove_skill(skill_name: str, request: Request):
    try:
        from openjarvis.agents.library import delete_skill

        delete_skill(skill_name)
        return {"deleted": True, "name": skill_name}
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# ---- Sessions routes ----

sessions_router = APIRouter(prefix="/v1/sessions", tags=["sessions"])


@sessions_router.get("")
async def list_sessions(request: Request, limit: int = 20):
    """List active sessions."""
    try:
        from openjarvis.sessions.store import SessionStore

        store = SessionStore()
        sessions = store.recent(limit=limit)
        items = [s.to_dict() if hasattr(s, "to_dict") else str(s) for s in sessions]
        return {"sessions": items}
    except Exception as exc:
        return {"sessions": [], "error": str(exc)}


@sessions_router.get("/{session_id}")
async def get_session(session_id: str, request: Request):
    """Get a specific session."""
    try:
        from openjarvis.sessions.store import SessionStore

        store = SessionStore()
        session = store.get(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="Session not found")
        return session.to_dict() if hasattr(session, "to_dict") else {"id": session_id}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# ---- Budget routes ----

budget_router = APIRouter(prefix="/v1/budget", tags=["budget"])

_budget_limits: Dict[str, Any] = {
    "max_tokens_per_day": None,
    "max_requests_per_hour": None,
}
_budget_usage: Dict[str, int] = {
    "tokens_today": 0,
    "requests_this_hour": 0,
}


@budget_router.get("")
async def get_budget(request: Request):
    """Get current budget usage and limits."""
    return {"limits": _budget_limits, "usage": _budget_usage}


@budget_router.put("/limits")
async def set_budget_limits(req: BudgetLimitsRequest, request: Request):
    """Update budget limits."""
    if req.max_tokens_per_day is not None:
        _budget_limits["max_tokens_per_day"] = req.max_tokens_per_day
    if req.max_requests_per_hour is not None:
        _budget_limits["max_requests_per_hour"] = req.max_requests_per_hour
    return {"status": "updated", "limits": _budget_limits}


# ---- Prometheus metrics ----

metrics_router = APIRouter(tags=["metrics"])


@metrics_router.get("/metrics")
async def prometheus_metrics(request: Request):
    """Prometheus-compatible metrics endpoint."""
    try:
        from openjarvis.core.config import DEFAULT_CONFIG_DIR
        from openjarvis.telemetry.aggregator import TelemetryAggregator

        db_path = DEFAULT_CONFIG_DIR / "telemetry.db"
        if not db_path.exists():
            from starlette.responses import PlainTextResponse

            return PlainTextResponse("# no telemetry data\n", media_type="text/plain")

        agg = TelemetryAggregator(db_path)
        stats = agg.summary()

        lines = [
            "# HELP openjarvis_requests_total Total requests processed",
            "# TYPE openjarvis_requests_total counter",
            f"openjarvis_requests_total {stats.get('total_requests', 0)}",
            "# HELP openjarvis_tokens_total Total tokens generated",
            "# TYPE openjarvis_tokens_total counter",
            f"openjarvis_tokens_total {stats.get('total_tokens', 0)}",
            "# HELP openjarvis_latency_avg_ms Average latency in milliseconds",
            "# TYPE openjarvis_latency_avg_ms gauge",
            f"openjarvis_latency_avg_ms {stats.get('avg_latency_ms', 0)}",
        ]
        from starlette.responses import PlainTextResponse

        return PlainTextResponse("\n".join(lines) + "\n", media_type="text/plain")
    except Exception as exc:
        logger.warning("Failed to collect Prometheus metrics: %s", exc)
        from starlette.responses import PlainTextResponse

        return PlainTextResponse("# No metrics available\n", media_type="text/plain")


# ---- WebSocket streaming routes ----

websocket_router = APIRouter(tags=["websocket"])


@websocket_router.websocket("/v1/chat/stream")
async def websocket_chat_stream(websocket: WebSocket):
    """Stream chat responses over a WebSocket connection.

    Accepts JSON messages of the form::

        {"message": "...", "model": "...", "agent": "..."}

    Sends back JSON chunks::

        {"type": "chunk", "content": "..."}   -- per-token streaming
        {"type": "done",  "content": "..."}   -- final assembled response
        {"type": "error", "detail": "..."}    -- on failure
    """
    await websocket.accept()
    try:
        while True:
            raw = await websocket.receive_text()
            try:
                data = json.loads(raw)
            except (json.JSONDecodeError, ValueError):
                await websocket.send_json(
                    {"type": "error", "detail": "Invalid JSON"},
                )
                continue

            message = data.get("message")
            if not message:
                await websocket.send_json(
                    {"type": "error", "detail": "Missing 'message' field"},
                )
                continue

            model = data.get("model") or getattr(
                websocket.app.state,
                "model",
                "default",
            )
            engine = getattr(websocket.app.state, "engine", None)
            if engine is None:
                await websocket.send_json(
                    {"type": "error", "detail": "No engine configured"},
                )
                continue

            messages = [{"role": "user", "content": message}]

            try:
                # Prefer streaming if the engine supports it
                stream_fn = getattr(engine, "stream", None)
                if stream_fn is not None and (
                    inspect.isasyncgenfunction(stream_fn) or callable(stream_fn)
                ):
                    full_content = ""
                    try:
                        gen = stream_fn(messages, model=model)
                        # Handle both async and sync generators
                        if inspect.isasyncgen(gen):
                            async for token in gen:
                                full_content += token
                                await websocket.send_json(
                                    {"type": "chunk", "content": token},
                                )
                        else:
                            # Sync generator — iterate in a thread to avoid
                            # blocking the event loop
                            for token in gen:
                                full_content += token
                                await websocket.send_json(
                                    {"type": "chunk", "content": token},
                                )
                    except TypeError:
                        # stream() didn't return an iterable; fall back to
                        # generate()
                        result = engine.generate(messages, model=model)
                        content = (
                            result.get("content", "")
                            if isinstance(
                                result,
                                dict,
                            )
                            else str(result)
                        )
                        full_content = content
                        await websocket.send_json(
                            {"type": "chunk", "content": content},
                        )
                    await websocket.send_json(
                        {"type": "done", "content": full_content},
                    )
                else:
                    # No stream method — single-shot generate
                    result = engine.generate(messages, model=model)
                    content = (
                        result.get("content", "")
                        if isinstance(
                            result,
                            dict,
                        )
                        else str(result)
                    )
                    await websocket.send_json(
                        {"type": "chunk", "content": content},
                    )
                    await websocket.send_json(
                        {"type": "done", "content": content},
                    )
            except WebSocketDisconnect:
                raise
            except Exception as exc:
                await websocket.send_json(
                    {"type": "error", "detail": str(exc)},
                )
    except WebSocketDisconnect:
        pass  # Client disconnected — nothing to clean up


# ---- Learning routes ----

learning_router = APIRouter(prefix="/v1/learning", tags=["learning"])


@learning_router.get("/stats")
async def learning_stats(request: Request):
    """Return learning system statistics across all sub-policies."""
    result: Dict[str, Any] = {}

    # Skill discovery
    try:
        from openjarvis.learning.agents.skill_discovery import SkillDiscovery

        discovery = SkillDiscovery()
        result["skill_discovery"] = {
            "available": True,
            "discovered_count": len(discovery.discovered_skills),
        }
    except Exception as exc:
        logger.warning("Failed to load skill discovery stats: %s", exc)
        result["skill_discovery"] = {"available": False}

    return result


@learning_router.get("/policy")
async def learning_policy(request: Request):
    """Return current routing policy configuration."""
    result: Dict[str, Any] = {}

    # Load config and extract learning section
    try:
        from openjarvis.core.config import load_config

        config = load_config()
        lc = config.learning
        result["enabled"] = lc.enabled
        result["update_interval"] = lc.update_interval
        result["auto_update"] = lc.auto_update
        result["routing"] = {
            "policy": lc.routing.policy,
            "min_samples": lc.routing.min_samples,
        }
        result["intelligence"] = {
            "policy": lc.intelligence.policy,
        }
        result["agent"] = {
            "policy": lc.agent.policy,
        }
        result["metrics"] = {
            "accuracy_weight": lc.metrics.accuracy_weight,
            "latency_weight": lc.metrics.latency_weight,
            "cost_weight": lc.metrics.cost_weight,
            "efficiency_weight": lc.metrics.efficiency_weight,
        }
    except Exception as exc:
        logger.warning("Failed to load learning config: %s", exc)
        result["enabled"] = False
        result["routing"] = {"policy": "heuristic", "min_samples": 5}
        result["intelligence"] = {"policy": "none"}
        result["agent"] = {"policy": "none"}
        result["metrics"] = {}

    return result


# ---- Speech routes ----

speech_router = APIRouter(prefix="/v1/speech", tags=["speech"])


@speech_router.post("/transcribe")
async def transcribe_speech(request: Request):
    """Transcribe uploaded audio to text."""
    import asyncio

    backend = getattr(request.app.state, "speech_backend", None)
    if backend is None:
        raise HTTPException(status_code=501, detail="Speech backend not configured")

    form = await request.form()
    audio_file = form.get("file")
    if audio_file is None:
        raise HTTPException(status_code=400, detail="Missing 'file' field")

    audio_bytes = await audio_file.read()
    language = form.get("language")

    # Detect format from filename
    filename = getattr(audio_file, "filename", "audio.wav")
    ext = filename.rsplit(".", 1)[-1] if "." in filename else "wav"

    result = await asyncio.to_thread(
        backend.transcribe,
        audio_bytes,
        format=ext,
        language=language or None,
    )
    return {
        "text": result.text,
        "language": result.language,
        "confidence": result.confidence,
        "duration_seconds": result.duration_seconds,
    }


@speech_router.get("/health")
async def speech_health(request: Request):
    """Check if a speech backend is available."""
    backend = getattr(request.app.state, "speech_backend", None)
    tts = getattr(request.app.state, "tts_backend", None)
    if backend is None and tts is None:
        return {"available": False, "reason": "No speech backend configured"}
    return {
        "available": backend.health() if backend else False,
        "backend": backend.backend_id if backend else None,
        "tts_available": tts.health() if tts else False,
        "tts_backend": tts.backend_id if tts else None,
    }


@speech_router.websocket("/stream")
async def speech_stream(websocket: WebSocket):
    """Stream STT: client sends 16kHz mono int16 PCM frames, server emits transcripts.

    Protocol
    --------
    Client → server: binary frames (raw little-endian int16 PCM @ 16kHz mono).
    Client → server: text frames as JSON for control, e.g. ``{"type": "flush"}``
        to force-transcribe the current buffer.

    Server → client: JSON messages::

        {"type": "speech_start"}
        {"type": "partial", "text": "...so far..."}
        {"type": "final",   "text": "...", "is_final": true}
        {"type": "speech_end"}
        {"type": "error",   "detail": "..."}
    """
    import asyncio

    await websocket.accept()
    backend = getattr(websocket.app.state, "speech_backend", None)
    if backend is None or getattr(backend, "backend_id", "") != "faster-whisper":
        await websocket.send_json(
            {
                "type": "error",
                "detail": "Streaming STT requires the faster-whisper backend",
            }
        )
        await websocket.close()
        return

    try:
        from openjarvis.speech.streaming import StreamingTranscriber
    except ImportError as exc:
        await websocket.send_json(
            {"type": "error", "detail": f"Streaming unavailable: {exc}"}
        )
        await websocket.close()
        return

    language = websocket.query_params.get("language") or None
    try:
        transcriber = StreamingTranscriber(backend, language=language)
    except ImportError as exc:
        await websocket.send_json(
            {
                "type": "error",
                "detail": (
                    f"silero-vad not installed: {exc}. "
                    "Run: uv sync --extra speech"
                ),
            }
        )
        await websocket.close()
        return

    async def _emit(events) -> None:
        for ev in events:
            await websocket.send_json(
                {
                    "type": ev.type,
                    "text": ev.text,
                    "is_final": ev.is_final,
                }
            )

    async def _run(fn) -> bool:
        """Run a transcription step in a worker thread; report failures."""
        try:
            events = await asyncio.to_thread(lambda: list(fn()))
        except Exception as exc:
            logger.exception("Streaming transcription failed")
            try:
                await websocket.send_json(
                    {"type": "error", "detail": f"Transcription failed: {exc}"}
                )
            except Exception:
                pass
            return False
        await _emit(events)
        return True

    try:
        while True:
            msg = await websocket.receive()
            if msg.get("type") == "websocket.disconnect":
                break
            if "bytes" in msg and msg["bytes"] is not None:
                ok = await _run(lambda b=msg["bytes"]: transcriber.feed_int16(b))
                if not ok:
                    break
            elif "text" in msg and msg["text"] is not None:
                try:
                    payload = json.loads(msg["text"])
                except (json.JSONDecodeError, ValueError):
                    continue
                if payload.get("type") == "flush":
                    ok = await _run(lambda: transcriber.flush())
                    if not ok:
                        break
                elif payload.get("type") == "reset":
                    transcriber.reset()
    except WebSocketDisconnect:
        pass


class TTSSynthesizeRequest(BaseModel):
    text: str
    voice_id: str = ""
    speed: float = 1.0
    output_format: str = "wav"


def _resolve_voice(request: Request, voice_id: str):
    """Map a voice_id to (backend, kwargs) for synthesize/stream.

    Custom voices live in :mod:`openjarvis.speech.custom_voices` — a mix
    expands to a comma-string passed to Kokoro; a clone routes to the F5-TTS
    backend with the reference audio path. Built-in IDs and empty strings
    fall through to the default TTS backend.
    """
    from openjarvis.speech import custom_voices

    default_tts = getattr(request.app.state, "tts_backend", None)
    clone_tts = getattr(request.app.state, "tts_clone_backend", None)

    if voice_id.startswith(("mix_", "clone_")):
        voice = custom_voices.get_voice(voice_id)
        if voice is None:
            raise HTTPException(status_code=404, detail=f"Unknown voice: {voice_id}")
        if voice.kind == "mix":
            return default_tts, {"voice_id": voice.kokoro_voice}
        # clone
        if clone_tts is None:
            raise HTTPException(
                status_code=501,
                detail=(
                    "Voice cloning backend not available. Install the "
                    "speech-clone extras and restart: uv sync --extra speech-clone"
                ),
            )
        kwargs = {"voice_id": voice.ref_audio}
        if voice.ref_text:
            kwargs["ref_text"] = voice.ref_text
        return clone_tts, kwargs

    return default_tts, ({"voice_id": voice_id} if voice_id else {})


@speech_router.post("/synthesize")
async def synthesize_speech(req: TTSSynthesizeRequest, request: Request):
    """Synthesize text to a single audio blob (non-streaming)."""
    from fastapi.responses import Response

    backend, voice_kwargs = _resolve_voice(request, req.voice_id)
    if backend is None:
        raise HTTPException(status_code=501, detail="TTS backend not configured")
    kwargs: Dict[str, Any] = {
        "speed": req.speed,
        "output_format": req.output_format,
        **voice_kwargs,
    }
    try:
        result = backend.synthesize(req.text, **kwargs)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    mime = "audio/wav" if result.format.lower() == "wav" else f"audio/{result.format}"
    return Response(content=result.audio, media_type=mime)


@speech_router.post("/synthesize/stream")
async def synthesize_speech_stream(req: TTSSynthesizeRequest, request: Request):
    """Synthesize text and stream sentence-sized audio chunks as SSE.

    Each event has ``audio`` (base64 WAV bytes), ``format``, ``sample_rate``,
    and ``text`` (the sentence rendered). A terminal ``[DONE]`` line marks
    end-of-stream.
    """
    import asyncio
    import base64

    from fastapi.responses import StreamingResponse

    backend, voice_kwargs = _resolve_voice(request, req.voice_id)
    if backend is None:
        raise HTTPException(status_code=501, detail="TTS backend not configured")

    stream_kwargs: Dict[str, Any] = {
        "speed": req.speed,
        "output_format": req.output_format,
        **voice_kwargs,
    }

    async def event_stream():
        try:
            it = await asyncio.to_thread(
                lambda: iter(backend.stream(req.text, **stream_kwargs))
            )
            while True:
                chunk = await asyncio.to_thread(next, it, None)
                if chunk is None:
                    break
                payload = {
                    "audio": base64.b64encode(chunk.audio).decode("ascii"),
                    "format": chunk.format,
                    "sample_rate": chunk.sample_rate,
                    "text": chunk.text,
                }
                yield f"data: {json.dumps(payload)}\n\n"
        except Exception as exc:
            err = json.dumps({"error": str(exc)})
            yield f"data: {err}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


@speech_router.get("/voices")
async def list_voices(request: Request):
    """Return available TTS voices, grouped by source.

    Response shape::

        {
          "backend": "kokoro",
          "clone_backend": "f5-tts" | null,
          "builtin": [{"id": "af_heart", "lang": "a", "gender": "f", "name": "heart"}, ...],
          "custom": [{"id": "mix_xxx", "name": "...", "kind": "mix", "kokoro_voice": "..."}, ...]
        }
    """
    from openjarvis.speech import custom_voices

    tts = getattr(request.app.state, "tts_backend", None)
    clone_tts = getattr(request.app.state, "tts_clone_backend", None)
    builtin = []
    if tts is not None:
        for v in tts.available_voices():
            entry: Dict[str, Any] = {"id": v}
            if len(v) >= 3 and v[2] == "_":
                entry["lang"] = v[0]
                entry["gender"] = v[1]
                entry["name"] = v[3:]
            builtin.append(entry)
    custom = [custom_voices.to_public_dict(v) for v in custom_voices.list_voices()]
    return {
        "backend": tts.backend_id if tts is not None else None,
        "clone_backend": clone_tts.backend_id if clone_tts is not None else None,
        "builtin": builtin,
        "custom": custom,
    }


class VoiceMixRequest(BaseModel):
    name: str
    voice_ids: List[str]


@speech_router.post("/voices/mix")
async def create_voice_mix(req: VoiceMixRequest, request: Request):
    """Save a named blend of built-in Kokoro voices."""
    from openjarvis.speech import custom_voices

    tts = getattr(request.app.state, "tts_backend", None)
    if tts is None or tts.backend_id != "kokoro":
        raise HTTPException(
            status_code=501,
            detail="Voice mixing requires the Kokoro TTS backend",
        )
    valid = set(tts.available_voices())
    bad = [v for v in req.voice_ids if v not in valid]
    if bad:
        raise HTTPException(status_code=400, detail=f"Unknown voice ID(s): {bad}")
    try:
        voice = custom_voices.add_mix(req.name, ",".join(req.voice_ids))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return custom_voices.to_public_dict(voice)


@speech_router.post("/voices/clone")
async def create_voice_clone(request: Request):
    """Upload a reference audio clip to create a cloned voice.

    Multipart fields: ``name`` (str), ``file`` (audio), ``ref_text`` (optional str).
    """
    from openjarvis.speech import custom_voices

    clone_tts = getattr(request.app.state, "tts_clone_backend", None)
    if clone_tts is None:
        raise HTTPException(
            status_code=501,
            detail=(
                "Voice cloning backend not installed. Install with: "
                "uv sync --extra speech-clone"
            ),
        )

    form = await request.form()
    name = (form.get("name") or "").strip()
    ref_text = (form.get("ref_text") or "").strip()
    audio_file = form.get("file")
    if audio_file is None or not hasattr(audio_file, "read"):
        raise HTTPException(status_code=400, detail="Missing audio file in 'file' field")
    audio_bytes = await audio_file.read()
    if len(audio_bytes) < 1024:
        raise HTTPException(status_code=400, detail="Audio file is too small (need ~6-10s of speech)")
    filename = getattr(audio_file, "filename", "ref.wav") or "ref.wav"
    suffix = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ".wav"
    try:
        voice = custom_voices.add_clone(name, audio_bytes, ref_text=ref_text, suffix=suffix)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return custom_voices.to_public_dict(voice)


@speech_router.delete("/voices/{voice_id}")
async def delete_voice(voice_id: str):
    from openjarvis.speech import custom_voices

    if not custom_voices.delete_voice(voice_id):
        raise HTTPException(status_code=404, detail="Voice not found")
    return {"deleted": voice_id}


# ---- Feedback routes ----

feedback_router = APIRouter(prefix="/v1/feedback", tags=["feedback"])


@feedback_router.post("")
async def submit_feedback(req: FeedbackScoreRequest, request: Request):
    """Submit feedback for a trace."""
    try:
        from openjarvis.core.config import DEFAULT_CONFIG_DIR
        from openjarvis.traces.store import TraceStore

        db_path = DEFAULT_CONFIG_DIR / "traces.db"
        if not db_path.exists():
            raise HTTPException(status_code=404, detail="No trace database")

        store = TraceStore(db_path)
        updated = store.update_feedback(req.trace_id, req.score)
        store.close()

        if not updated:
            raise HTTPException(
                status_code=404, detail=f"Trace '{req.trace_id}' not found"
            )
        return {"status": "recorded", "trace_id": req.trace_id}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@feedback_router.get("/stats")
async def feedback_stats(request: Request):
    """Get feedback statistics."""
    return {"total": 0, "mean_score": 0.0}


# ---- Optimize routes ----

optimize_router = APIRouter(prefix="/v1/optimize", tags=["optimize"])


@optimize_router.get("/runs")
async def list_optimize_runs(request: Request):
    """List optimization runs."""
    try:
        from openjarvis.core.config import DEFAULT_CONFIG_DIR
        from openjarvis.learning.optimize.store import OptimizationStore

        db_path = DEFAULT_CONFIG_DIR / "optimize.db"
        if not db_path.exists():
            return {"runs": []}

        store = OptimizationStore(db_path)
        runs = store.list_runs()
        store.close()
        return {"runs": runs}
    except Exception as exc:
        logger.warning("Failed to list optimization runs: %s", exc)
        return {"runs": []}


@optimize_router.get("/runs/{run_id}")
async def get_optimize_run(run_id: str, request: Request):
    """Get optimization run details."""
    try:
        from openjarvis.core.config import DEFAULT_CONFIG_DIR
        from openjarvis.learning.optimize.store import OptimizationStore

        db_path = DEFAULT_CONFIG_DIR / "optimize.db"
        if not db_path.exists():
            return {"run_id": run_id, "status": "not_found"}

        store = OptimizationStore(db_path)
        run = store.get_run(run_id)
        store.close()

        if run is None:
            return {"run_id": run_id, "status": "not_found"}

        return {
            "run_id": run.run_id,
            "status": run.status,
            "benchmark": run.benchmark,
            "trials": len(run.trials),
            "best_trial_id": (run.best_trial.trial_id if run.best_trial else None),
        }
    except Exception as exc:
        logger.warning("Failed to get optimization run %s: %s", run_id, exc)
        return {"run_id": run_id, "status": "not_found"}


@optimize_router.post("/runs")
async def start_optimize_run(req: OptimizeRunRequest, request: Request):
    """Start a new optimization run."""
    return {"status": "started", "run_id": "placeholder"}


def include_all_routes(app) -> None:
    """Include all extended API routers in a FastAPI app."""
    app.include_router(agents_router)
    app.include_router(memory_router)
    app.include_router(traces_router)
    app.include_router(telemetry_router)
    app.include_router(skills_router)
    app.include_router(sessions_router)
    app.include_router(budget_router)
    app.include_router(metrics_router)
    app.include_router(websocket_router)
    app.include_router(learning_router)
    app.include_router(speech_router)
    app.include_router(feedback_router)
    app.include_router(optimize_router)

    # Agent Manager routes (if available)
    try:
        if hasattr(app.state, "agent_manager") and app.state.agent_manager:
            from openjarvis.server.agent_manager_routes import (  # noqa: PLC0415
                create_agent_manager_router,
            )

            (
                agents_r,
                templates_r,
                global_r,
                tools_r,
                sendblue_r,
            ) = create_agent_manager_router(app.state.agent_manager)
            app.include_router(agents_r)
            app.include_router(templates_r)
            app.include_router(global_r)
            app.include_router(tools_r)
            app.include_router(sendblue_r)
    except ImportError:
        pass

    # WebSocket bridge for real-time agent events
    try:
        from openjarvis.core.events import get_event_bus
        from openjarvis.server.ws_bridge import create_ws_router

        ws_router = create_ws_router(get_event_bus())
        app.include_router(ws_router)
    except Exception:
        logger.debug("WebSocket bridge not available", exc_info=True)


__all__ = [
    "include_all_routes",
    "agents_router",
    "memory_router",
    "traces_router",
    "telemetry_router",
    "skills_router",
    "sessions_router",
    "budget_router",
    "metrics_router",
    "websocket_router",
    "learning_router",
    "speech_router",
    "feedback_router",
    "optimize_router",
]
