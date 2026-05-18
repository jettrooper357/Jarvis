"""``jarvis serve`` — OpenAI-compatible API server."""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional

import click
from rich.console import Console

from openjarvis.core.config import load_config
from openjarvis.core.events import EventBus
from openjarvis.engine import (
    discover_engines,
    discover_models,
    get_engine,
)
from openjarvis.intelligence import (
    merge_discovered_models,
    register_builtin_models,
)

logger = logging.getLogger(__name__)


def _find_uv() -> Optional[str]:
    """Locate the ``uv`` binary.

    Checks PATH, ``~/.local/bin``, and ``~/.cargo/bin`` — uv's default install
    locations. Returns ``None`` if not found so callers can fall back to pip.
    """
    found = shutil.which("uv")
    if found:
        return found
    for candidate in (
        Path.home() / ".local" / "bin" / "uv",
        Path.home() / ".cargo" / "bin" / "uv",
    ):
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    return None


def _install_clone_backend(console: Console) -> bool:
    """Run ``uv sync --extra speech-clone`` (or pip equivalent).

    Returns True on success. Streams the installer's stdout/stderr through
    Rich so the user sees the download progress instead of a silent block.
    """
    uv = _find_uv()
    if uv is not None:
        cmd = [uv, "sync", "--extra", "speech-clone"]
    else:
        # uv missing — fall back to plain pip in the running interpreter's venv.
        cmd = [sys.executable, "-m", "pip", "install", "f5-tts>=0.3"]

    console.print(f"[yellow]Installing voice-cloning backend:[/yellow] {' '.join(cmd)}")
    console.print("[dim]This may take several minutes and download ~1.4 GB.[/dim]")
    try:
        proc = subprocess.run(cmd, check=False)
    except OSError as exc:
        console.print(f"[red]Installer failed to launch: {exc}[/red]")
        return False
    if proc.returncode != 0:
        console.print(
            f"[red]Install exited with code {proc.returncode}.[/red] "
            "See output above; you can retry manually with the command shown."
        )
        return False
    console.print("[green]Voice-cloning backend installed.[/green]")
    return True


def _has_clone_voices() -> bool:
    """True if the user has saved any cloned voices and would expect F5 to work."""
    try:
        from openjarvis.speech import custom_voices

        return any(v.kind == "clone" for v in custom_voices.list_voices())
    except Exception:
        return False


def _try_load_clone_backend():
    """Return an F5-TTS instance if importable and healthy, else None."""
    try:
        # Re-import speech package so newly-installed modules register.
        import importlib

        import openjarvis.speech as _speech_pkg
        from openjarvis.core.registry import TTSRegistry

        importlib.reload(_speech_pkg)

        if not TTSRegistry.contains("f5-tts"):
            return None
        candidate = TTSRegistry.get("f5-tts")()
        return candidate if candidate.health() else None
    except Exception as exc:  # pragma: no cover — environment-dependent
        logger.debug("Clone backend load failed: %s", exc)
        return None


def _discover_clone_backend(console: Console, *, force_install: bool):
    """Locate (and optionally install) the voice-cloning backend.

    Install conditions, in order: an explicit ``--install-clone`` flag, then
    the presence of stored clone voices (the user has already opted in by
    creating one). Silent otherwise — clone is genuinely optional.
    """
    backend = _try_load_clone_backend()
    if backend is not None:
        return backend

    should_install = force_install or _has_clone_voices()
    if not should_install:
        return None

    if not _install_clone_backend(console):
        return None

    backend = _try_load_clone_backend()
    if backend is None:
        console.print(
            "[yellow]Install completed but F5-TTS still won't import. "
            "Try restarting `jarvis serve` so a fresh Python process picks "
            "up the new modules.[/yellow]"
        )
    return backend


@click.command()
@click.option("--host", default=None, help="Bind address (default: config).")
@click.option(
    "--port",
    default=None,
    type=int,
    help="Port number (default: config).",
)
@click.option("-e", "--engine", "engine_key", default=None, help="Engine backend.")
@click.option("-m", "--model", "model_name", default=None, help="Default model.")
@click.option(
    "-a",
    "--agent",
    "agent_name",
    default=None,
    help="Agent for non-streaming requests (simple, orchestrator, react, openhands).",
)
@click.option(
    "--install-clone",
    is_flag=True,
    default=False,
    help=(
        "If the voice-cloning backend (F5-TTS) is missing, run "
        "`uv sync --extra speech-clone` before starting the server."
    ),
)
def serve(
    host: str | None,
    port: int | None,
    engine_key: str | None,
    model_name: str | None,
    agent_name: str | None,
    install_clone: bool,
) -> None:
    """Start the OpenAI-compatible API server."""
    console = Console(stderr=True)

    # Check for server dependencies
    try:
        import uvicorn  # noqa: F401
        from fastapi import FastAPI  # noqa: F401
    except ImportError:
        console.print(
            "[red bold]Server dependencies not installed.[/red bold]\n\n"
            "Install the server extra:\n"
            "  [cyan]uv sync --extra server[/cyan]"
        )
        sys.exit(1)

    config = load_config()

    # Resolve host/port from CLI args or config
    bind_host = host or config.server.host
    bind_port = port or config.server.port

    # Set up engine
    register_builtin_models()
    bus = EventBus(record_history=False)

    # Set up telemetry
    telem_store = None
    if config.telemetry.enabled:
        try:
            from pathlib import Path

            from openjarvis.telemetry.store import TelemetryStore

            db_path = Path(config.telemetry.db_path).expanduser()
            db_path.parent.mkdir(parents=True, exist_ok=True)
            telem_store = TelemetryStore(str(db_path))
            telem_store.subscribe_to_bus(bus)
        except Exception as exc:
            logger.debug("Telemetry store init failed: %s", exc)

    resolved = get_engine(config, engine_key)
    if resolved is None:
        console.print(
            "[red bold]No inference engine available.[/red bold]\n\n"
            "Make sure an engine is running."
        )
        sys.exit(1)

    engine_name, engine = resolved

    # Apply security guardrails
    from openjarvis.security import setup_security

    sec = setup_security(config, engine, bus)
    engine = sec.engine

    # If cloud API keys are set, wrap with MultiEngine so both local
    # and cloud models appear in the model list and can be used.
    import os

    _has_cloud = (
        os.environ.get("OPENAI_API_KEY")
        or os.environ.get("ANTHROPIC_API_KEY")
        or os.environ.get("GEMINI_API_KEY")
        or os.environ.get("GOOGLE_API_KEY")
        or os.environ.get("OPENROUTER_API_KEY")
    )
    if _has_cloud and engine_name != "cloud":
        try:
            from openjarvis.engine.cloud import CloudEngine
            from openjarvis.engine.multi import MultiEngine

            cloud = CloudEngine()
            engine = MultiEngine([(engine_name, engine), ("cloud", cloud)])
            engine_name = "multi"
            if cloud.health():
                console.print("  Cloud:  [cyan]enabled[/cyan] (API keys detected)")
            else:
                console.print(
                    "  Cloud:  [yellow]keys set but packages missing[/yellow] "
                    "(run: uv sync --extra inference-cloud --extra inference-google)"
                )
        except Exception as exc:
            logger.debug("Cloud engine init failed: %s", exc)

    # Wrap engine with InstrumentedEngine for telemetry recording
    try:
        from openjarvis.telemetry.instrumented_engine import InstrumentedEngine

        energy_mon = None
        try:
            from openjarvis.telemetry.energy_monitor import create_energy_monitor

            energy_mon = create_energy_monitor()
            if energy_mon is not None:
                console.print(
                    f"  Energy: [cyan]{energy_mon.vendor().value}[/cyan] "
                    f"({energy_mon.energy_method()})"
                )
        except Exception as exc:
            logger.debug("Energy monitor creation failed: %s", exc)

        engine = InstrumentedEngine(engine, bus, energy_monitor=energy_mon)
    except Exception as exc:
        logger.debug("Engine instrumentation failed: %s", exc)

    # Discover models
    all_engines = discover_engines(config)
    all_models = discover_models(all_engines)
    for ek, model_ids in all_models.items():
        merge_discovered_models(ek, model_ids)

    # Resolve model
    if model_name is None:
        model_name = config.server.model or config.intelligence.default_model
    if not model_name:
        engine_models = all_models.get(engine_name, [])
        if engine_models:
            model_name = engine_models[0]
        else:
            console.print("[red]No model available on engine.[/red]")
            sys.exit(1)

    # Resolve agent
    agent = None
    agent_key = agent_name or config.server.agent
    if agent_key:
        try:
            import openjarvis.agents  # noqa: F401
            from openjarvis.core.registry import AgentRegistry

            if AgentRegistry.contains(agent_key):
                agent_cls = AgentRegistry.get(agent_key)
                agent_kwargs = {"bus": bus}
                if sec.capability_policy is not None:
                    agent_kwargs["capability_policy"] = sec.capability_policy

                # Load tools for agents that support them
                if getattr(agent_cls, "accepts_tools", False):
                    import openjarvis.tools  # noqa: F401  # trigger registration
                    from openjarvis.core.registry import ToolRegistry
                    from openjarvis.tools._stubs import BaseTool

                    _DEFAULT_TOOLS = {"think", "calculator", "web_search"}
                    configured = config.agent.tools
                    if configured:
                        if isinstance(configured, list):
                            allowed = {
                                t.strip()
                                for t in configured
                                if isinstance(t, str) and t.strip()
                            }
                        else:
                            allowed = {
                                t.strip() for t in configured.split(",") if t.strip()
                            }
                    else:
                        allowed = _DEFAULT_TOOLS

                    tools = []
                    for name in ToolRegistry.keys():
                        if name not in allowed:
                            continue
                        tool_cls = ToolRegistry.get(name)
                        if isinstance(tool_cls, type) and issubclass(
                            tool_cls, BaseTool
                        ):
                            tools.append(tool_cls())
                        elif isinstance(tool_cls, BaseTool):
                            tools.append(tool_cls)
                    if tools:
                        agent_kwargs["tools"] = tools

                if getattr(agent_cls, "accepts_tools", False):
                    agent_kwargs["max_turns"] = config.agent.max_turns

                agent = agent_cls(engine, model_name, **agent_kwargs)
        except Exception as exc:
            import traceback

            console.print(f"[yellow]Agent '{agent_key}' failed to load: {exc}[/yellow]")
            traceback.print_exc()

    # Set up channel backend if enabled
    channel_bridge = None
    # Always try to build a channel: _resolve_channel honors config.toml first
    # but also bootstraps from UI-saved credential files (e.g. telegram.json)
    # so users who set their bot token in the UI don't have to also edit
    # config.toml to flip channel.enabled.
    try:
        from openjarvis.system import SystemBuilder

        sb = SystemBuilder(config)
        sb._bus = bus
        channel_bridge = sb._resolve_channel(config, bus)
        if channel_bridge is not None:
            channel_bridge.connect()
            channel_label = (
                config.channel.default_channel
                if (config.channel.enabled and config.channel.default_channel)
                else getattr(channel_bridge, "channel_id", "channel")
            )
            console.print(f"  Channel: [cyan]{channel_label}[/cyan]")
    except Exception as exc:
        console.print(f"[yellow]Channel failed to start: {exc}[/yellow]")
        channel_bridge = None

    # Build the fallback system used by ChannelBridge when an incoming chat
    # does not match a managed-agent binding.
    channel_system = None
    if channel_bridge is not None:
        from openjarvis.system import JarvisSystem

        channel_agent = config.channel.default_agent or agent_key or "simple"

        _channel_tools: list = []
        if channel_agent:
            try:
                import openjarvis.agents
                from openjarvis.core.registry import AgentRegistry

                if AgentRegistry.contains(channel_agent):
                    _ch_cls = AgentRegistry.get(channel_agent)
                    if getattr(_ch_cls, "accepts_tools", False):
                        import openjarvis.tools
                        from openjarvis.core.registry import ToolRegistry
                        from openjarvis.tools._stubs import BaseTool

                        _DEFAULT_TOOLS = {"think", "calculator", "web_search"}
                        configured = config.agent.tools
                        if configured:
                            if isinstance(configured, list):
                                _allowed = {
                                    t.strip()
                                    for t in configured
                                    if isinstance(t, str) and t.strip()
                                }
                            else:
                                _allowed = {
                                    t.strip()
                                    for t in configured.split(",")
                                    if t.strip()
                                }
                        else:
                            _allowed = _DEFAULT_TOOLS

                        for _tname in ToolRegistry.keys():
                            if _tname not in _allowed:
                                continue
                            _tcls = ToolRegistry.get(_tname)
                            if isinstance(_tcls, type) and issubclass(_tcls, BaseTool):
                                _channel_tools.append(_tcls())
                            elif isinstance(_tcls, BaseTool):
                                _channel_tools.append(_tcls)
            except Exception as exc:
                logger.warning("Channel tools failed to load: %s", exc)

        channel_system = JarvisSystem(
            config=config,
            bus=bus,
            engine=engine,
            engine_key=engine_name,
            model=model_name,
            agent_name=channel_agent,
            tools=_channel_tools,
        )

    # Set up speech backend
    speech_backend = None
    try:
        from openjarvis.speech._discovery import get_speech_backend

        speech_backend = get_speech_backend(config)
        if speech_backend:
            console.print(f"  Speech: [cyan]{speech_backend.backend_id}[/cyan]")
    except Exception as exc:
        logger.debug("Speech backend discovery failed: %s", exc)

    tts_backend = None
    try:
        from openjarvis.speech._tts_discovery import get_tts_backend

        tts_backend = get_tts_backend(config)
        if tts_backend:
            console.print(f"  TTS:    [cyan]{tts_backend.backend_id}[/cyan]")
    except Exception as exc:
        logger.debug("TTS backend discovery failed: %s", exc)

    # Voice cloning backend — separate from the default TTS so users can keep
    # Kokoro for built-in voices and switch only cloned voices to F5-TTS.
    tts_clone_backend = _discover_clone_backend(
        console,
        force_install=install_clone,
    )
    if tts_clone_backend is not None:
        console.print(f"  Clone:  [cyan]{tts_clone_backend.backend_id}[/cyan]")

    # Create app
    from openjarvis.server.app import create_app

    # Set up agent manager
    agent_manager = None
    if config.agent_manager.enabled:
        try:
            from pathlib import Path

            from openjarvis.agents.manager import AgentManager

            am_db = config.agent_manager.db_path or str(
                Path("~/.openjarvis/agents.db").expanduser()
            )
            agent_manager = AgentManager(db_path=am_db)
        except Exception as exc:
            logger.debug("Agent manager init failed: %s", exc)

    # Set up agent scheduler for cron/interval agents
    agent_scheduler = None
    if agent_manager is not None:
        try:
            from openjarvis.agents.executor import AgentExecutor
            from openjarvis.agents.scheduler import AgentScheduler

            _trace_store = None
            try:
                if config.traces.enabled:
                    from openjarvis.traces.store import TraceStore

                    _trace_store = TraceStore(db_path=config.traces.db_path)
            except Exception:
                pass

            executor = AgentExecutor(
                manager=agent_manager,
                event_bus=bus,
                trace_store=_trace_store,
            )
            from openjarvis.system import SystemBuilder

            system = SystemBuilder(config).build()
            executor.set_system(system)

            agent_scheduler = AgentScheduler(
                manager=agent_manager,
                executor=executor,
                event_bus=bus,
            )
            for ag in agent_manager.list_agents():
                if ag["status"] not in (
                    "archived",
                    "error",
                ):
                    agent_scheduler.register_agent(ag["id"])
            agent_scheduler.start()
            console.print("  Scheduler: [cyan]active[/cyan]")
        except Exception as exc:
            logger.debug("Agent scheduler init failed: %s", exc)

    # Set up memory backend for context injection
    memory_backend = None
    if config.agent.context_from_memory:
        try:
            import openjarvis.tools.storage  # noqa: F401
            from openjarvis.core.registry import MemoryRegistry

            mem_key = config.memory.default_backend
            if MemoryRegistry.contains(mem_key):
                memory_backend = MemoryRegistry.create(
                    mem_key,
                    db_path=config.memory.db_path,
                )
                console.print("  Memory:    [cyan]active[/cyan]")
        except Exception as exc:
            logger.debug("Memory backend init failed: %s", exc)

    # --- Channel Gateway: API key, sessions, ChannelBridge ---
    import os as _os

    api_key = _os.environ.get("OPENJARVIS_API_KEY", "")
    if not api_key:
        try:
            import tomllib

            _cfg_path = str(
                __import__("pathlib").Path.home() / ".openjarvis" / "config.toml"
            )
            with open(_cfg_path, "rb") as _f:
                _raw = tomllib.load(_f)
            api_key = _raw.get("server", {}).get("auth", {}).get("api_key", "")
        except (FileNotFoundError, ImportError):
            pass

    from openjarvis.server.auth_middleware import check_bind_safety

    check_bind_safety(bind_host, api_key=api_key)

    # Log credential status at startup
    from openjarvis.core.credentials import TOOL_CREDENTIALS, get_credential_status

    _cred_parts = []
    for _tool_name in sorted(TOOL_CREDENTIALS):
        _status = get_credential_status(_tool_name)
        _set = sum(1 for v in _status.values() if v)
        _total = len(_status)
        if _set > 0:
            _cred_parts.append(f"{_tool_name}: {_set}/{_total} keys")
    if _cred_parts:
        logger.info("Credentials loaded — %s", ", ".join(_cred_parts))

    webhook_config = {
        "twilio_auth_token": _os.environ.get("TWILIO_AUTH_TOKEN", ""),
        "bluebubbles_password": _os.environ.get("BLUEBUBBLES_PASSWORD", ""),
        "whatsapp_verify_token": _os.environ.get("WHATSAPP_VERIFY_TOKEN", ""),
        "whatsapp_app_secret": _os.environ.get("WHATSAPP_APP_SECRET", ""),
    }

    # Wrap existing channel in ChannelBridge orchestrator
    if channel_bridge is not None:
        try:
            from openjarvis.server.channel_bridge import (
                ChannelBridge,
            )
            from openjarvis.server.session_store import (
                SessionStore,
            )

            session_store = SessionStore()
            channels = {channel_bridge.channel_id: channel_bridge}
            channel_bridge = ChannelBridge(
                channels=channels,
                session_store=session_store,
                bus=bus,
                system=channel_system,
                agent_manager=agent_manager,
                engine=engine,
                default_model=model_name or "",
            )
        except Exception as exc:
            logger.debug("ChannelBridge init skipped: %s", exc)

    app = create_app(
        engine,
        model_name,
        agent=agent,
        bus=bus,
        engine_name=engine_name,
        agent_name=agent_key or "",
        channel_bridge=channel_bridge,
        config=config,
        memory_backend=memory_backend,
        speech_backend=speech_backend,
        tts_backend=tts_backend,
        tts_clone_backend=tts_clone_backend,
        agent_manager=agent_manager,
        agent_scheduler=agent_scheduler,
        api_key=api_key,
        webhook_config=webhook_config,
        cors_origins=config.server.cors_origins,
    )

    console.print(
        f"[green]Starting OpenJarvis API server[/green]\n"
        f"  Engine: [cyan]{engine_name}[/cyan]\n"
        f"  Model:  [cyan]{model_name}[/cyan]\n"
        f"  Agent:  [cyan]{agent_key or 'none'}[/cyan]\n"
        f"  URL:    [cyan]http://{bind_host}:{bind_port}[/cyan]"
    )

    # Warn about wildcard CORS on non-loopback
    import ipaddress as _ipa

    try:
        _is_loop = _ipa.ip_address(bind_host).is_loopback
    except ValueError:
        _is_loop = bind_host in ("localhost", "")

    if not _is_loop and "*" in config.server.cors_origins:
        console.print(
            "[yellow bold]WARNING:[/yellow bold] Wildcard CORS with credentials "
            "enabled on non-loopback interface. This allows any website to make "
            "authenticated requests to your instance."
        )

    # Surface native crashes (segfaults / access violations inside torch,
    # audio, STT/TTS or other C extensions) as a Python traceback instead of
    # a silent process exit back to the shell. Without this, an extension
    # fault leaves no diagnostics at all.
    import faulthandler

    import uvicorn

    try:
        if not faulthandler.is_enabled():
            faulthandler.enable(all_threads=True)
    except Exception:
        pass

    uvicorn.run(app, host=bind_host, port=bind_port, log_level="info")
