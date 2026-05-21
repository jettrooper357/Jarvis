#!/usr/bin/env python3
"""Live Chief Orchestrator demo: chief + two subordinates against a real engine.

Idempotently creates three managed agents in the user's configured DB:

- ``Demo Chief`` -- orchestrator_mode=chief, no manager
- ``Demo Worker A`` -- researcher, manager_agent_id = Demo Chief
- ``Demo Worker B`` -- researcher, manager_agent_id = Demo Chief

...then sends a sample request through ``ManagedAgentRuntime``, prints the
chief's final response, and dumps the recent transcripts for each agent
so you can see the action JSON and the delegation calls.

Usage::

    python scripts/chief_demo.py
    python scripts/chief_demo.py --prompt "Your request here"
    python scripts/chief_demo.py --model qwen2.5:7b --verbose

Re-running is safe -- existing agents with the same names are reused and
their config is patched in place.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from textwrap import indent
from typing import Any, Dict, Optional

from openjarvis.agents.manager import AgentManager
from openjarvis.core.config import load_config
from openjarvis.core.events import EventBus
from openjarvis.engine._discovery import get_engine
from openjarvis.intelligence.model_catalog import register_builtin_models
from openjarvis.security import setup_security
from openjarvis.server.managed_agent_runtime import ManagedAgentRuntime
from openjarvis.traces.store import TraceStore

CHIEF_NAME = "Demo Chief"
LEAF_A_NAME = "Demo Worker A"
LEAF_B_NAME = "Demo Worker B"

WORKER_PROMPT = (
    "You are a focused researcher. Answer the question crisply in 3-5 "
    "sentences. Cover strengths, weaknesses, and a final score from 1 to 10."
)

DEFAULT_PROMPT = (
    "Briefly compare two observability backends -- Prometheus and Datadog -- "
    "and recommend one for a small self-hosted setup."
)


def ensure_agent(
    manager: AgentManager,
    *,
    name: str,
    agent_type: str,
    org_role: str,
    config: Dict[str, Any],
    manager_agent_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Create or update the named agent so its config/hierarchy match."""
    existing = next(
        (
            agent
            for agent in manager.list_agents(include_archived=False)
            if agent.get("name") == name
        ),
        None,
    )
    if existing is not None:
        updates: Dict[str, Any] = {}
        if existing.get("org_role") != org_role:
            updates["org_role"] = org_role
        if existing.get("agent_type") != agent_type:
            updates["agent_type"] = agent_type
        if (existing.get("config") or {}) != config:
            updates["config"] = config
        if updates:
            manager.update_agent(existing["id"], **updates)
        if (
            manager_agent_id is not None
            and existing.get("manager_agent_id") != manager_agent_id
        ):
            manager.update_agent(
                existing["id"], manager_agent_id=manager_agent_id
            )
        return manager.get_agent(existing["id"])  # type: ignore[return-value]
    return manager.create_agent(
        name=name,
        agent_type=agent_type,
        org_role=org_role,
        config=config,
        manager_agent_id=manager_agent_id,
    )


def _resolve_model(args_model: Optional[str], cfg: Any, engine: Any) -> str:
    if args_model:
        return args_model
    model = cfg.intelligence.default_model or getattr(engine, "_model", "") or ""
    if model:
        return model
    try:
        models = engine.list_models()
    except Exception:
        models = []
    return models[0] if models else ""


def _print_transcript(manager: AgentManager, agent: Dict[str, Any]) -> None:
    print(f"\n--- {agent['name']} ({agent['id']}) ---")
    messages = list(manager.list_messages(agent["id"], limit=10))
    if not messages:
        print("  (no messages)")
        return
    for entry in reversed(messages):
        direction = entry.get("direction", "?")
        content = entry.get("content", "") or ""
        if len(content) > 800:
            content = content[:800] + " [...]"
        print(f"  [{direction}]")
        print(indent(content, "    "))


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--prompt",
        default=DEFAULT_PROMPT,
        help=f"User request to send to the chief (default: {DEFAULT_PROMPT!r}).",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="Override the model for all three demo agents.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable INFO-level logging.",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )

    cfg = load_config()
    register_builtin_models()
    bus = EventBus(record_history=False)

    print("Bootstrapping engine...")
    resolved = get_engine(cfg)
    if resolved is None:
        print(
            "ERROR: no inference engine available. "
            "Make sure Ollama (or your configured engine) is running."
        )
        return 2
    engine_name, engine = resolved
    sec = setup_security(cfg, engine, bus)
    engine = sec.engine
    print(f"  Engine: {engine_name}")

    model = _resolve_model(args.model, cfg, engine)
    if not model:
        print(
            "ERROR: no model configured. Pass --model "
            "or set intelligence.default_model in config.toml."
        )
        return 2
    print(f"  Model:  {model}")

    db_path = cfg.agent_manager.db_path or str(
        Path("~/.openjarvis/agents.db").expanduser()
    )
    manager = AgentManager(db_path=db_path)
    traces_path = cfg.traces.db_path or str(
        Path("~/.openjarvis/traces.db").expanduser()
    )
    trace_store = TraceStore(traces_path)
    print(f"  DB:     {db_path}")
    print(f"  Traces: {traces_path}\n")

    worker_config = {
        "model": model,
        "system_prompt": WORKER_PROMPT,
        "max_turns": 1,
        "temperature": 0.3,
        "max_tokens": 384,
    }

    leaf_a = ensure_agent(
        manager,
        name=LEAF_A_NAME,
        agent_type="monitor_operative",
        org_role="researcher",
        config=worker_config,
    )
    leaf_b = ensure_agent(
        manager,
        name=LEAF_B_NAME,
        agent_type="monitor_operative",
        org_role="researcher",
        config=worker_config,
    )
    chief = ensure_agent(
        manager,
        name=CHIEF_NAME,
        agent_type="monitor_operative",
        org_role="chief orchestrator",
        config={
            "model": model,
            "orchestrator_mode": "chief",
            "max_turns": 4,
            "temperature": 0.2,
            "max_tokens": 1024,
        },
    )
    for leaf in (leaf_a, leaf_b):
        if leaf.get("manager_agent_id") != chief["id"]:
            manager.update_agent(leaf["id"], manager_agent_id=chief["id"])
    # Re-fetch so we have the latest hierarchy/config
    chief = manager.get_agent(chief["id"]) or chief
    leaf_a = manager.get_agent(leaf_a["id"]) or leaf_a
    leaf_b = manager.get_agent(leaf_b["id"]) or leaf_b

    print(f"  Chief:      {chief['name']} ({chief['id']})")
    print(f"  Worker A:   {leaf_a['name']} ({leaf_a['id']})")
    print(f"  Worker B:   {leaf_b['name']} ({leaf_b['id']})")

    runtime = ManagedAgentRuntime(
        manager,
        engine,
        bus=bus,
        default_model=model,
        trace_store=trace_store,
    )

    print(f"\n>>> User -> {chief['name']}:")
    print(indent(args.prompt, "    "))
    print("\n(running -- this may take a moment depending on the model)...\n")

    import time as _time

    run_started_at = _time.time()
    try:
        response = runtime.run(chief["id"], args.prompt)
    except Exception as exc:
        print(f"ERROR: chief run failed: {exc}")
        return 1

    print(f"<<< {chief['name']}:")
    print(indent(response, "    "))

    print("\n" + "=" * 72)
    print("TRANSCRIPTS (newest last)")
    print("=" * 72)
    for agent in (chief, leaf_a, leaf_b):
        _print_transcript(manager, agent)

    print("\n" + "=" * 72)
    print("TRACE TREE")
    print("=" * 72)
    _print_trace_tree(
        trace_store,
        manager=manager,
        chief_id=chief["id"],
        started_at_floor=run_started_at,
    )

    return 0


def _print_trace_tree(
    trace_store: TraceStore,
    *,
    manager: AgentManager,
    chief_id: str,
    started_at_floor: float,
) -> None:
    """Locate this run's root trace and walk its children, indented."""
    all_rows = trace_store._fetchall()
    candidates = [
        trace_store._row_to_trace(r)
        for r in all_rows
        if r[9] >= started_at_floor  # column 9 = started_at
    ]
    roots = [
        t for t in candidates if t.parent_trace_id is None and t.agent == chief_id
    ]
    if not roots:
        print("  (no root trace recorded for this run)")
        return
    root = max(roots, key=lambda t: t.started_at)

    def _label(trace) -> str:
        agent_rec = manager.get_agent(trace.agent)
        name = agent_rec.get("name", trace.agent) if agent_rec else trace.agent
        latency = f"{trace.total_latency_seconds:.1f}s"
        return f"{name} [{trace.trace_id}] ({trace.outcome or '?'}, {latency})"

    def _walk(trace, depth: int = 0) -> None:
        bullet = "  " * depth + ("- " if depth else "* ")
        print(bullet + _label(trace))
        result_snippet = trace.result.replace("\n", " ")[:160]
        if result_snippet:
            print("  " * (depth + 1) + 'result: "' + result_snippet + '"')
        for child in trace_store.list_children(trace.trace_id):
            _walk(child, depth + 1)

    _walk(root)
    family = trace_store.list_by_run(root.run_id or root.trace_id)
    print(f"\n  run_id={root.run_id}  total traces in run: {len(family)}")


if __name__ == "__main__":
    sys.exit(main())
