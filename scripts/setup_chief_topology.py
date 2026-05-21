#!/usr/bin/env python3
"""Set up the minimum chief-mode agent topology for the chat page.

Creates two managed agents idempotently in the user's configured
``agents.db``:

- **Chief Orchestrator** (chief mode on, no manager) -- the agent the
  chat page resolves to by default. Routes user requests through the
  action envelope. Has project tools attached because its ``org_role``
  matches ``PROJECT_TOOL_ROLES``.
- **Project Manager** (subordinate of the chief) -- a standard-mode
  agent the chief can delegate to. Also gets project tools from the
  same role-based attachment.

After running this you can ask the chat:

    "Create a new project called Jarvis."

...and watch the chief either delegate to the Project Manager or call
``project_create`` itself via ``action=execute_direct``.

Re-running is safe -- existing agents with the same names get their
config patched in place and their hierarchy reasserted.

Usage::

    python scripts/setup_chief_topology.py
    python scripts/setup_chief_topology.py --model qwen3.5:2b
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from textwrap import indent
from typing import Any, Dict, Optional

from openjarvis.agents.manager import AgentManager
from openjarvis.core.config import load_config

CHIEF_NAME = "Chief Orchestrator"
PROJECT_MANAGER_NAME = "Project Manager"


def ensure_agent(
    manager: AgentManager,
    *,
    name: str,
    agent_type: str,
    org_role: str,
    config: Dict[str, Any],
    manager_agent_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Create the named agent if absent; patch config/role if present."""
    existing = next(
        (
            a
            for a in manager.list_agents(include_archived=False)
            if a.get("name") == name
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
        return manager.get_agent(existing["id"]) or existing
    return manager.create_agent(
        name=name,
        agent_type=agent_type,
        org_role=org_role,
        config=config,
        manager_agent_id=manager_agent_id,
    )


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--model",
        default=None,
        help=(
            "Model the agents will run on. Defaults to "
            "intelligence.default_model from config.toml; if unset, leaves "
            "the field blank and lets the runtime fall back to the chat's "
            "selected model."
        ),
    )
    parser.add_argument(
        "--chief-name",
        default=CHIEF_NAME,
        help=f"Name for the chief (default: {CHIEF_NAME!r}).",
    )
    parser.add_argument(
        "--manager-name",
        default=PROJECT_MANAGER_NAME,
        help=f"Name for the project-manager subordinate (default: {PROJECT_MANAGER_NAME!r}).",
    )
    args = parser.parse_args(argv)

    cfg = load_config()
    model = args.model or cfg.intelligence.default_model or ""

    db_path = cfg.agent_manager.db_path or str(
        Path("~/.openjarvis/agents.db").expanduser()
    )
    manager = AgentManager(db_path=db_path)
    print(f"DB:    {db_path}")
    print(f"Model: {model or '(unset -- runtime fallback)'}\n")

    chief_config: Dict[str, Any] = {
        "orchestrator_mode": "chief",
        "max_turns": 6,
        "temperature": 0.2,
        "max_tokens": 1024,
    }
    if model:
        chief_config["model"] = model

    chief = ensure_agent(
        manager,
        name=args.chief_name,
        agent_type="monitor_operative",
        org_role="chief orchestrator",
        config=chief_config,
    )

    pm_config: Dict[str, Any] = {
        "max_turns": 4,
        "temperature": 0.3,
        "max_tokens": 1024,
        "system_prompt": (
            "You are a project manager. When the chief asks you to create "
            "or manage a project, call the appropriate project_* tool "
            "(project_create, project_create_task, project_update_task, "
            "etc.) and report back the result. Keep your replies short."
        ),
    }
    if model:
        pm_config["model"] = model

    project_manager = ensure_agent(
        manager,
        name=args.manager_name,
        agent_type="monitor_operative",
        org_role="project manager",
        config=pm_config,
        manager_agent_id=chief["id"],
    )

    # Re-fetch so we report current state
    chief = manager.get_agent(chief["id"]) or chief
    project_manager = (
        manager.get_agent(project_manager["id"]) or project_manager
    )

    print("Topology ready:\n")
    print(
        indent(
            f"{chief['name']}\n"
            f"  id:           {chief['id']}\n"
            f"  org_role:     {chief.get('org_role', '')}\n"
            f"  chief mode:   {chief.get('config', {}).get('orchestrator_mode') == 'chief'}\n"
            f"  manager:      (none)\n",
            "  ",
        )
    )
    print(
        indent(
            f"{project_manager['name']}\n"
            f"  id:           {project_manager['id']}\n"
            f"  org_role:     {project_manager.get('org_role', '')}\n"
            f"  manager:      {project_manager.get('manager_agent_id', '')}\n",
            "  ",
        )
    )

    print("How to test:")
    print(
        "  1. Restart the server (or just refresh the chat page if it's"
        " already running)."
    )
    print(
        f"  2. In the chat box: \"Create a new project called Jarvis.\""
    )
    print(
        "  3. The chief will either call project_create itself"
        " (action=execute_direct) or delegate to the Project Manager"
        " (action=delegate). Either way you should see the project show"
        " up on the Projects page."
    )
    print(
        "  4. Open the agent in the Agents page -> Logs tab ->"
        " 'Show call tree' on the latest trace to see the action path."
    )

    manager.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
