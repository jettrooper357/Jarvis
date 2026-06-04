"""FastAPI application factory for the OpenJarvis API server."""

from __future__ import annotations

import logging
import pathlib
import time

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from openjarvis.core.config import DEFAULT_CONFIG_DIR
from openjarvis.server.api_routes import include_all_routes
from openjarvis.server.comparison import comparison_router
from openjarvis.server.connectors_router import (
    create_connectors_router,
    start_connector_autosync_loop,
)
from openjarvis.server.dashboard import dashboard_router
from openjarvis.server.digest_routes import create_digest_router
from openjarvis.server.projects_router import create_projects_router
from openjarvis.server.routes import router
from openjarvis.server.shortcuts_router import create_shortcuts_router
from openjarvis.server.upload_router import router as upload_router
from openjarvis.server.watchtower_routes import create_watchtower_router

logger = logging.getLogger(__name__)


def _restore_sendblue_bindings(app: FastAPI) -> None:
    """Restore SendBlue channel bindings from the database on startup.

    If a SendBlue binding was created via the Messaging tab and the server
    restarts, this ensures the ChannelBridge + DeepResearchAgent are wired
    up so incoming webhooks continue to work.
    """
    try:
        mgr = getattr(app.state, "agent_manager", None)
        if mgr is None:
            return

        # Check all agents for sendblue bindings
        for agent in mgr.list_agents():
            agent_id = agent.get("id", agent.get("agent_id", ""))
            bindings = mgr.list_channel_bindings(agent_id)
            for b in bindings:
                if b.get("channel_type") != "sendblue":
                    continue
                config = b.get("config", {})
                api_key_id = config.get("api_key_id", "")
                api_secret_key = config.get("api_secret_key", "")
                from_number = config.get("from_number", "")
                if not api_key_id or not api_secret_key:
                    continue

                from openjarvis.channels.sendblue import SendBlueChannel

                sb = SendBlueChannel(
                    api_key_id=api_key_id,
                    api_secret_key=api_secret_key,
                    from_number=from_number,
                )
                sb.connect()
                app.state.sendblue_channel = sb

                # Create ChannelBridge if none exists
                bridge = getattr(app.state, "channel_bridge", None)
                if bridge and hasattr(bridge, "_channels"):
                    if hasattr(bridge, "add_channel"):
                        bridge.add_channel("sendblue", sb)
                    else:
                        bridge._channels["sendblue"] = sb
                else:
                    from openjarvis.server.channel_bridge import ChannelBridge
                    from openjarvis.server.session_store import SessionStore

                    session_store = SessionStore()
                    engine = getattr(app.state, "engine", None)
                    dr_agent = None
                    if engine:
                        from openjarvis.server.agent_manager_routes import (
                            _build_deep_research_tools,
                        )

                        tools = _build_deep_research_tools(engine=engine, model="")
                        if tools:
                            from openjarvis.agents.deep_research import (
                                DeepResearchAgent,
                            )

                            model_name = getattr(app.state, "model", "") or getattr(
                                engine, "_model", ""
                            )
                            dr_agent = DeepResearchAgent(
                                engine=engine,
                                model=model_name,
                                tools=tools,
                            )

                    bus = getattr(app.state, "bus", None)
                    if bus is None:
                        from openjarvis.core.events import EventBus

                        bus = EventBus()

                    app.state.channel_bridge = ChannelBridge(
                        channels={"sendblue": sb},
                        session_store=session_store,
                        bus=bus,
                        agent_manager=mgr,
                        deep_research_agent=dr_agent,
                    )

                logger.info(
                    "Restored SendBlue channel binding: %s",
                    from_number,
                )
                return  # Only need one SendBlue binding
    except Exception as exc:
        logger.debug("SendBlue binding restore skipped: %s", exc)


# No-cache headers applied to static file responses
_NO_CACHE_HEADERS = {
    "Cache-Control": "no-cache, no-store, must-revalidate",
    "Pragma": "no-cache",
    "Expires": "0",
}


class _NoCacheStaticFiles(StaticFiles):
    """StaticFiles subclass that adds no-cache headers to every response."""

    async def __call__(self, scope, receive, send):
        async def _send_with_headers(message):
            if message["type"] == "http.response.start":
                extra = [(k.encode(), v.encode()) for k, v in _NO_CACHE_HEADERS.items()]
                # Remove etag and last-modified
                existing = [
                    (k, v)
                    for k, v in message.get("headers", [])
                    if k.lower() not in (b"etag", b"last-modified")
                ]
                message = {**message, "headers": existing + extra}
            await send(message)

        await super().__call__(scope, receive, _send_with_headers)


def create_app(
    engine,
    model: str,
    *,
    agent=None,
    bus=None,
    engine_name: str = "",
    agent_name: str = "",
    channel_bridge=None,
    config=None,
    memory_backend=None,
    speech_backend=None,
    tts_backend=None,
    tts_clone_backend=None,
    agent_manager=None,
    agent_scheduler=None,
    api_key: str = "",
    webhook_config: dict | None = None,
    cors_origins: list[str] | None = None,
) -> FastAPI:
    """Create and configure the FastAPI application.

    Parameters
    ----------
    engine:
        The inference engine to use for completions.
    model:
        Default model name.
    agent:
        Optional agent instance for agent-mode completions.
    bus:
        Optional event bus for telemetry.
    channel_bridge:
        Optional channel bridge for multi-platform messaging.
    config:
        Optional JarvisConfig for other settings.
    """
    app = FastAPI(
        title="OpenJarvis API",
        description="OpenAI-compatible API server for OpenJarvis",
        version="0.1.0",
    )

    from fastapi.middleware.cors import CORSMiddleware

    _origins = (
        cors_origins
        if cors_origins is not None
        else [
            "http://localhost:5173",
            "http://127.0.0.1:5173",
            # Tauri 2 production webview origins:
            #   macOS / Linux / iOS  -> tauri://localhost
            #   Windows / Android    -> http://tauri.localhost (default),
            #                           https://tauri.localhost when
            #                           windows.useHttpsScheme is enabled
            "tauri://localhost",
            "http://tauri.localhost",
            "https://tauri.localhost",
        ]
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Store dependencies in app state
    app.state.engine = engine
    app.state.model = model
    app.state.agent = agent
    app.state.bus = bus
    app.state.engine_name = engine_name

    # Auto-attach the cloud engine when API keys are present, so cloud
    # models (gpt-*, claude-*, …) route to the provider for *every* path
    # (chat and agent), not just when the desktop app calls
    # /v1/cloud/reload. Without this, a cloud model selected with a saved
    # key still reaches the local Ollama engine and fails.
    try:
        import os as _os
        from pathlib import Path as _Path

        keys_path = _Path.home() / ".openjarvis" / "cloud-keys.env"
        if keys_path.exists():
            for _raw in keys_path.read_text().splitlines():
                _line = _raw.strip()
                if _line and not _line.startswith("#") and "=" in _line:
                    _k, _v = _line.split("=", 1)
                    _os.environ[_k.strip()] = _v.strip()
        _key_names = (
            "OPENAI_API_KEY",
            "ANTHROPIC_API_KEY",
            "GEMINI_API_KEY",
            "GOOGLE_API_KEY",
            "OPENROUTER_API_KEY",
        )
        if any(_os.environ.get(_n) for _n in _key_names):
            from openjarvis.engine.cloud import CloudEngine
            from openjarvis.engine.multi import MultiEngine

            _cloud = CloudEngine()
            if _cloud.health():
                _outer = app.state.engine
                _inner = getattr(_outer, "_inner", _outer)
                if isinstance(_inner, MultiEngine):
                    _inner._engines = [
                        (k, e) for k, e in _inner._engines if k != "cloud"
                    ] + [("cloud", _cloud)]
                    _inner._refresh_map()
                else:
                    _nm = engine_name or "local"
                    _multi = MultiEngine(
                        [(_nm, _inner), ("cloud", _cloud)]
                    )
                    if hasattr(_outer, "_inner"):
                        _outer._inner = _multi
                    else:
                        app.state.engine = _multi
                    app.state.engine_name = "multi"
                if app.state.agent is not None and hasattr(
                    app.state.agent, "_engine"
                ):
                    app.state.agent._engine = app.state.engine
                logger.info(
                    "Cloud engine auto-attached (API keys detected)"
                )
    except Exception:
        logger.debug("Cloud engine auto-attach skipped", exc_info=True)
    app.state.agent_name = agent_name or (
        getattr(agent, "agent_id", None) if agent else None
    )
    app.state.channel_bridge = channel_bridge
    app.state.config = config
    app.state.memory_backend = memory_backend
    app.state.speech_backend = speech_backend
    app.state.tts_backend = tts_backend
    app.state.tts_clone_backend = tts_clone_backend
    app.state.agent_manager = agent_manager
    # Reap agents left 'running' by an interrupted prior run (restart/crash)
    # so the dashboard is accurate and they become runnable again.
    try:
        _reaped = agent_manager.reap_stale_running()
        if _reaped:
            logging.getLogger(__name__).info(
                "Reaped %d stale 'running' agent(s) on startup", _reaped
            )
    except Exception:
        logging.getLogger(__name__).exception(
            "Stale-agent reaper failed on startup"
        )
    app.state.agent_scheduler = agent_scheduler
    app.state.session_start = time.time()

    # Phase 2D — approval store. Colocated in the agent DB so approval
    # rows join cleanly against agents/tasks. The approvals API and the
    # tool-dispatch gate both read it from ``app.state``; both degrade
    # gracefully when it is absent.
    app.state.approval_store = None
    try:
        if agent_manager is not None:
            from openjarvis.agents.approvals import ApprovalStore

            app.state.approval_store = ApprovalStore(
                agent_manager._db_path,
                event_bus=getattr(app.state, "bus", None),
            )
    except Exception:
        logging.getLogger(__name__).exception(
            "Failed to initialise ApprovalStore"
        )

    # Wire up trace store if traces are enabled
    app.state.trace_store = None
    try:
        from openjarvis.core.config import load_config
        from openjarvis.traces.store import TraceStore

        cfg = config if config is not None else load_config()
        if cfg.traces.enabled:
            _trace_store = TraceStore(db_path=cfg.traces.db_path)
            app.state.trace_store = _trace_store
            _bus = getattr(app.state, "bus", None)
            if _bus is not None:
                _trace_store.subscribe_to_bus(_bus)
    except Exception:
        pass  # traces are optional; don't block server startup

    # Wire up the persisted event log if enabled
    app.state.event_log_store = None
    try:
        from openjarvis.core.config import load_config
        from openjarvis.eventlog.store import EventLogStore

        cfg = config if config is not None else load_config()
        if cfg.eventlog.enabled:
            _event_log_store = EventLogStore(db_path=cfg.eventlog.db_path)
            app.state.event_log_store = _event_log_store
            _bus = getattr(app.state, "bus", None)
            if _bus is not None:
                _event_log_store.subscribe_to_bus(
                    _bus, denylist=cfg.eventlog.denylist
                )
    except Exception:
        pass  # event log is optional; don't block server startup

    # Wire up the generalized action-approval store if enabled
    app.state.action_approval_store = None
    try:
        from openjarvis.approvals_center.store import ActionApprovalStore
        from openjarvis.core.config import load_config

        cfg = config if config is not None else load_config()
        if cfg.action_approvals.enabled:
            app.state.action_approval_store = ActionApprovalStore(
                db_path=cfg.action_approvals.db_path
            )
    except Exception:
        pass  # action approvals are optional; don't block server startup

    # Wire up Task–Code Linkage if enabled
    app.state.codelink_store = None
    app.state.codelink_watchers = None
    try:
        from openjarvis.codelink.store import CodeLinkStore
        from openjarvis.codelink.watcher import start_watchers
        from openjarvis.core.config import load_config

        cfg = config if config is not None else load_config()
        if cfg.codelink.enabled:
            _codelink_store = CodeLinkStore(db_path=cfg.codelink.db_path)
            app.state.codelink_store = _codelink_store
            if cfg.codelink.watch_enabled:
                from openjarvis.projects.store import ProjectStore

                projects = ProjectStore().list_projects()
                app.state.codelink_watchers = start_watchers(
                    _codelink_store, projects, enabled=True
                )
    except Exception:
        pass  # code linkage is optional; don't block server startup

    # Wire up the Life Manager store if enabled
    app.state.life_store = None
    try:
        from openjarvis.core.config import load_config
        from openjarvis.lifemanager.store import LifeStore

        cfg = config if config is not None else load_config()
        if cfg.lifemanager.enabled:
            app.state.life_store = LifeStore(db_path=cfg.lifemanager.db_path)
    except Exception:
        pass  # life manager is optional; don't block server startup

    # Wire up the Controlled Autonomy rollback store if enabled
    app.state.rollback_store = None
    try:
        from openjarvis.autonomy.rollback_store import RollbackStore
        from openjarvis.core.config import load_config

        cfg = config if config is not None else load_config()
        if cfg.autonomy.enabled:
            app.state.rollback_store = RollbackStore(
                db_path=cfg.autonomy.db_path
            )
    except Exception:
        pass  # autonomy is optional; don't block server startup

    # Wire up Jarvis Watchtower. It owns separate additive tables and must
    # never block the existing server if unavailable.
    app.state.watchtower_store = None
    app.state.watchtower_service = None
    try:
        from openjarvis.channels.telegram import TelegramChannel
        from openjarvis.projects.store import ProjectStore
        from openjarvis.watchtower.service import WatchtowerService
        from openjarvis.watchtower.store import WatchtowerStore
        from openjarvis.watchtower.types import WatchtowerSettings

        wt_store = WatchtowerStore()
        wt_settings = WatchtowerSettings.from_dict(wt_store.get_settings())
        app.state.watchtower_store = wt_store
        telegram_channel = None
        telegram_chat_id = ""
        if wt_settings.telegram_enabled:
            try:
                telegram_channel = TelegramChannel(
                    bus=getattr(app.state, "bus", None)
                )
                allowed = getattr(telegram_channel, "_allowed_chat_ids", "") or ""
                telegram_chat_id = str(allowed).split(",", 1)[0].strip()
            except Exception:
                telegram_channel = None
        app.state.watchtower_service = WatchtowerService(
            store=wt_store,
            settings=wt_settings,
            project_store=ProjectStore(),
            agent_manager=agent_manager,
            approval_store=getattr(app.state, "approval_store", None),
            event_bus=getattr(app.state, "bus", None),
            telegram_channel=telegram_channel,
            telegram_chat_id=telegram_chat_id,
            tts_backend=getattr(app.state, "tts_backend", None),
            provider_config={
                "engine": wt_settings.local_ai_provider
                or getattr(app.state, "engine_name", "")
            },
            engine=getattr(app.state, "engine", None),
        )
    except Exception:
        logging.getLogger(__name__).exception(
            "Failed to initialise Watchtower"
        )

    @app.on_event("startup")
    async def _warm_up_models() -> None:
        """Preload STT/TTS/LLM weights off the request path so the *first*
        interaction isn't penalised by cold model loads (latency target:
        speech-end -> first token < 2s; models stay resident afterwards).

        Best-effort and fully isolated: runs in a daemon thread so server
        startup never blocks, and every stage is guarded so a missing model
        or offline runtime degrades gracefully instead of crashing.
        """
        import asyncio
        import inspect
        import threading

        try:
            start_connector_autosync_loop()
        except Exception:
            logger.exception("Failed to start connector autosync loop")

        def _warm() -> None:
            sb = getattr(app.state, "speech_backend", None)
            ensure = getattr(sb, "_ensure_model", None)
            if callable(ensure):
                try:
                    ensure()
                except Exception as exc:
                    logger.warning("STT warm-up skipped: %s", exc)

            tb = getattr(app.state, "tts_backend", None)
            if tb is not None:
                try:
                    tb.synthesize("Ready.", output_format="wav")
                except Exception as exc:
                    logger.warning("TTS warm-up skipped: %s", exc)

            eng = getattr(app.state, "engine", None)
            mdl = getattr(app.state, "model", None)
            gen = getattr(eng, "generate", None)
            if callable(gen) and mdl:
                try:
                    from openjarvis.core.types import Message, Role

                    args = ([Message(role=Role.USER, content="hi")],)
                    kw = {"model": mdl, "max_tokens": 1}
                    if inspect.iscoroutinefunction(gen):
                        asyncio.run(gen(*args, **kw))
                    else:
                        gen(*args, **kw)
                except Exception as exc:
                    logger.warning("LLM warm-up skipped: %s", exc)

        threading.Thread(target=_warm, name="jarvis-warmup", daemon=True).start()

        wt_service = getattr(app.state, "watchtower_service", None)
        try:
            if wt_service is not None:
                wt_service.start()
        except Exception:
            logger.exception("Watchtower startup failed")

    @app.on_event("shutdown")
    async def _stop_watchtower() -> None:
        wt_service = getattr(app.state, "watchtower_service", None)
        try:
            if wt_service is not None:
                wt_service.stop()
        except Exception:
            logger.exception("Watchtower shutdown failed")

    app.include_router(router)
    app.include_router(dashboard_router)
    app.include_router(comparison_router)
    app.include_router(create_connectors_router())
    app.include_router(create_projects_router())
    app.include_router(create_digest_router())
    app.include_router(create_shortcuts_router())
    app.include_router(create_watchtower_router())
    app.include_router(upload_router)
    uploads_dir = DEFAULT_CONFIG_DIR / "data" / "uploads"
    uploads_dir.mkdir(parents=True, exist_ok=True)
    app.mount(
        "/uploads",
        _NoCacheStaticFiles(directory=uploads_dir),
        name="uploads",
    )
    include_all_routes(app)

    # Restore SendBlue channel bindings from database on startup
    _restore_sendblue_bindings(app)

    # Add security headers middleware
    try:
        from openjarvis.server.middleware import create_security_middleware

        middleware_cls = create_security_middleware()
        if middleware_cls is not None:
            app.add_middleware(middleware_cls)
    except Exception as exc:
        logger.debug("Security middleware init skipped: %s", exc)

    # API key authentication middleware
    if api_key:
        try:
            from openjarvis.server.auth_middleware import AuthMiddleware

            app.add_middleware(AuthMiddleware, api_key=api_key)
        except Exception as exc:
            logger.debug("Auth middleware init skipped: %s", exc)

    # Mount webhook routes (always — SendBlue may be configured dynamically)
    if webhook_config:
        try:
            from openjarvis.server.webhook_routes import (
                create_webhook_router,
            )

            webhook_router = create_webhook_router(
                bridge=channel_bridge,
                twilio_auth_token=webhook_config.get("twilio_auth_token", ""),
                bluebubbles_password=webhook_config.get("bluebubbles_password", ""),
                whatsapp_verify_token=webhook_config.get("whatsapp_verify_token", ""),
                whatsapp_app_secret=webhook_config.get("whatsapp_app_secret", ""),
            )
            app.include_router(webhook_router)
        except Exception as exc:
            logger.debug("Webhook routes init skipped: %s", exc)

    # Serve static frontend assets if the static/ directory exists
    static_dir = pathlib.Path(__file__).parent / "static"
    if static_dir.is_dir():
        assets_dir = static_dir / "assets"
        if assets_dir.is_dir():
            app.mount(
                "/assets",
                _NoCacheStaticFiles(directory=assets_dir),
                name="static-assets",
            )

        @app.get("/{full_path:path}")
        async def spa_catch_all(full_path: str):
            """Serve static files directly, fall back to index.html for SPA routes."""
            if full_path:
                candidate = (static_dir / full_path).resolve()
                # Path traversal prevention
                resolved_root = static_dir.resolve()
                if candidate.is_relative_to(resolved_root) and candidate.is_file():
                    return FileResponse(candidate, headers=_NO_CACHE_HEADERS)
            return FileResponse(
                static_dir / "index.html",
                headers=_NO_CACHE_HEADERS,
            )

    return app


__all__ = ["create_app"]
