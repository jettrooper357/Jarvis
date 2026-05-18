"""Managed-agent capability resolution for tools, knowledge, and skills."""

from __future__ import annotations

import importlib
import logging
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from openjarvis.agents.library import (
    builtin_skills_dir,
    user_skills_dir,
    workspace_skills_dir,
)
from openjarvis.core.registry import ToolRegistry
from openjarvis.skills.executor import SkillExecutor
from openjarvis.skills.manager import SkillManager
from openjarvis.skills.tool_adapter import SkillTool
from openjarvis.tools._stubs import BaseTool, ToolExecutor

logger = logging.getLogger(__name__)

AUTO_COLLABORATION_TOOLS = (
    "managed_agent_directory",
    "managed_agent_delegate",
    "managed_agent_message",
    "managed_agent_assign_task",
    "managed_agent_list_tasks",
    "managed_agent_update_task",
    "managed_agent_inspect",
)
AUTO_PROJECT_TOOLS = ("project_create", "project_create_task", "project_list")
PROJECT_TOOL_ROLES = (
    "chief orchestrator",
    "chief executive officer",
    "ceo",
    "chief of staff",
    "chief operating officer",
    "coo",
    "workflow manager",
    "project manager",
)
KNOWLEDGE_TOOL_NAMES = ("knowledge_search", "knowledge_sql", "scan_chunks", "think")
KNOWLEDGE_ENABLED_AGENT_TYPES = {"deep_research", "monitor_operative", "operative"}


def configured_agent_tool_names(agent_record: Dict[str, Any]) -> List[str]:
    config = agent_record.get("config", {}) or {}
    names: List[str] = []
    for entry in config.get("tools") or []:
        if isinstance(entry, str):
            cleaned = entry.strip()
            if cleaned and cleaned not in names:
                names.append(cleaned)
    return names


def configured_agent_skill_names(agent_record: Dict[str, Any]) -> List[str]:
    config = agent_record.get("config", {}) or {}
    raw_skills = config.get("skills") or []
    if isinstance(raw_skills, str):
        raw_skills = [part.strip() for part in raw_skills.split(",")]
    names: List[str] = []
    for entry in raw_skills:
        if isinstance(entry, str):
            cleaned = entry.strip()
            if cleaned and cleaned not in names:
                names.append(cleaned)
    return names


def should_enable_agent_knowledge(agent_record: Dict[str, Any]) -> bool:
    from openjarvis.core.config import DEFAULT_CONFIG_DIR

    config = agent_record.get("config", {}) or {}
    if config.get("knowledge_enabled") is False:
        return False
    agent_type = str(agent_record.get("agent_type", "")).strip()
    if agent_type not in KNOWLEDGE_ENABLED_AGENT_TYPES:
        return False
    return (DEFAULT_CONFIG_DIR / "knowledge.db").exists()


def should_enable_project_tools(agent_record: Dict[str, Any]) -> bool:
    role = str(agent_record.get("org_role", "") or "").strip().casefold()
    name = str(agent_record.get("name", "") or "").strip().casefold()
    haystack = f"{role} {name}"
    return any(marker in haystack for marker in PROJECT_TOOL_ROLES)


def effective_agent_tool_names(agent_record: Dict[str, Any]) -> List[str]:
    names = configured_agent_tool_names(agent_record)
    if str(agent_record.get("name", "")).strip() or agent_record.get("id"):
        for tool_name in AUTO_COLLABORATION_TOOLS:
            if tool_name not in names:
                names.append(tool_name)
    if should_enable_project_tools(agent_record):
        for tool_name in AUTO_PROJECT_TOOLS:
            if tool_name not in names:
                names.append(tool_name)
    if should_enable_agent_knowledge(agent_record):
        agent_type = str(agent_record.get("agent_type", "")).strip()
        auto_knowledge = (
            list(KNOWLEDGE_TOOL_NAMES)
            if agent_type == "deep_research"
            else ["knowledge_search"]
        )
        for tool_name in auto_knowledge:
            if tool_name not in names:
                names.append(tool_name)
    return names


def enrich_agent_record(agent_record: Dict[str, Any]) -> Dict[str, Any]:
    config = agent_record.get("config", {}) or {}
    configured_tools = configured_agent_tool_names(agent_record)
    configured_skills = configured_agent_skill_names(agent_record)
    effective_tools = effective_agent_tool_names(agent_record)
    auto_tools = [name for name in effective_tools if name not in configured_tools]
    enriched = dict(agent_record)
    enriched["template_id"] = str(config.get("template_id", "") or "")
    enriched["configured_tools"] = configured_tools
    enriched["configured_skills"] = configured_skills
    enriched["effective_skills"] = configured_skills
    enriched["auto_tools"] = auto_tools
    enriched["effective_tools"] = effective_tools
    enriched["knowledge_enabled"] = "knowledge_search" in effective_tools
    return enriched


def _ensure_tool_registries_populated() -> None:
    try:
        import openjarvis.tools  # noqa: F401
    except Exception:
        pass

    missing = not ToolRegistry.keys()
    if missing:
        for module_name in list(sys.modules):
            if module_name.startswith("openjarvis.tools.") and not module_name.endswith(
                "_stubs"
            ):
                try:
                    importlib.reload(sys.modules[module_name])
                except Exception:
                    logger.exception("Failed to reload tool module %s", module_name)


def _build_knowledge_tools(engine: Any, model: str) -> Dict[str, BaseTool]:
    from openjarvis.connectors.retriever import TwoStageRetriever
    from openjarvis.connectors.store import KnowledgeStore
    from openjarvis.core.config import DEFAULT_CONFIG_DIR
    from openjarvis.tools.knowledge_search import KnowledgeSearchTool
    from openjarvis.tools.knowledge_sql import KnowledgeSQLTool
    from openjarvis.tools.scan_chunks import ScanChunksTool
    from openjarvis.tools.think import ThinkTool

    knowledge_db_path = DEFAULT_CONFIG_DIR / "knowledge.db"
    if not Path(knowledge_db_path).exists():
        return {"think": ThinkTool()}

    store = KnowledgeStore(str(knowledge_db_path))
    retriever = TwoStageRetriever(store)
    return {
        "knowledge_search": KnowledgeSearchTool(retriever=retriever),
        "knowledge_sql": KnowledgeSQLTool(store=store),
        "scan_chunks": ScanChunksTool(store=store, engine=engine, model=model),
        "think": ThinkTool(),
    }


def _skill_paths() -> List[Path]:
    paths: List[Path] = []
    for path in (workspace_skills_dir(), user_skills_dir(), builtin_skills_dir()):
        if path.exists() and path not in paths:
            paths.append(path)
    return paths


def _collect_skill_tool_dependencies(
    skill_name: str,
    manager: SkillManager,
    collected: set[str],
    seen: set[str],
) -> None:
    if skill_name in seen:
        return
    seen.add(skill_name)
    manifest = manager.resolve(skill_name)
    for step in manifest.steps:
        if step.skill_name:
            _collect_skill_tool_dependencies(step.skill_name, manager, collected, seen)
            continue
        if step.tool_name:
            collected.add(step.tool_name)


def build_agent_tool_instances(
    agent_record: Dict[str, Any],
    *,
    engine: Any,
    model: str,
    bus: Any = None,
    capability_policy: Any = None,
    execution_context: Any = None,
    interactive: bool = False,
    confirm_callback: Optional[Callable[[str], bool]] = None,
    inject_tool: Optional[Callable[[BaseTool], None]] = None,
) -> List[BaseTool]:
    """Build the exact callable tool set for a managed agent."""
    _ensure_tool_registries_populated()

    visible_tool_names = effective_agent_tool_names(agent_record)
    selected_skill_names = configured_agent_skill_names(agent_record)
    skill_manager: Optional[SkillManager] = None
    selected_skill_manifests: List[Any] = []
    hidden_skill_tools: set[str] = set()

    if selected_skill_names:
        try:
            skill_manager = SkillManager(bus, capability_policy=capability_policy)
            skill_manager.discover(paths=_skill_paths())
            seen_skill_names: set[str] = set()
            for skill_name in selected_skill_names:
                try:
                    manifest = skill_manager.resolve(skill_name)
                except KeyError:
                    logger.warning("Skill '%s' is not installed", skill_name)
                    continue
                selected_skill_manifests.append(manifest)
                _collect_skill_tool_dependencies(
                    skill_name,
                    skill_manager,
                    hidden_skill_tools,
                    seen_skill_names,
                )
        except Exception:
            logger.exception("Failed to initialize skill manager for managed agent")
            skill_manager = None
            selected_skill_manifests = []
            hidden_skill_tools = set()

    all_tool_names: List[str] = []
    for tool_name in [*visible_tool_names, *sorted(hidden_skill_tools)]:
        cleaned = str(tool_name or "").strip()
        if cleaned and cleaned not in all_tool_names:
            all_tool_names.append(cleaned)

    knowledge_instances: Dict[str, BaseTool] = {}
    if any(name in KNOWLEDGE_TOOL_NAMES for name in all_tool_names):
        try:
            knowledge_instances = _build_knowledge_tools(engine, model)
        except Exception:
            logger.exception("Failed to build knowledge tools")

    instantiated_by_name: Dict[str, BaseTool] = {}
    for tool_name in all_tool_names:
        if tool_name in instantiated_by_name:
            continue
        tool: Optional[BaseTool] = None
        if tool_name in knowledge_instances:
            tool = knowledge_instances[tool_name]
        elif ToolRegistry.contains(tool_name):
            tool_cls = ToolRegistry.get(tool_name)
            try:
                if tool_name in AUTO_COLLABORATION_TOOLS:
                    tool = tool_cls(context=execution_context)
                else:
                    tool = tool_cls()
            except Exception:
                logger.exception("Failed to instantiate tool %s", tool_name)
                continue
        else:
            logger.warning("Tool '%s' is not registered", tool_name)
            continue
        if inject_tool is not None:
            try:
                inject_tool(tool)
            except Exception:
                logger.exception("Failed to inject dependencies for tool %s", tool_name)
        instantiated_by_name[tool.spec.name] = tool

    visible_tools: List[BaseTool] = []
    for tool_name in visible_tool_names:
        tool = instantiated_by_name.get(tool_name)
        if tool is not None and tool.spec.name not in [
            t.spec.name for t in visible_tools
        ]:
            visible_tools.append(tool)

    if skill_manager is not None and selected_skill_manifests:
        try:
            hidden_executor = ToolExecutor(
                list(instantiated_by_name.values()),
                bus=bus,
                interactive=interactive,
                confirm_callback=confirm_callback,
                capability_policy=capability_policy,
                agent_id=str(agent_record.get("id", "") or ""),
            )
            skill_manager.set_tool_executor(hidden_executor)
            resolver = skill_manager._make_resolver()
            for manifest in selected_skill_manifests:
                if skill_manager._tool_executor is None:
                    continue
                skill_exec = SkillExecutor(skill_manager._tool_executor, bus=bus)
                skill_exec.set_skill_resolver(resolver)
                visible_tools.append(
                    SkillTool(manifest, skill_exec, skill_manager=skill_manager)
                )
        except Exception:
            logger.exception("Failed to build skill tools for managed agent")

    deduped: List[BaseTool] = []
    seen_names: set[str] = set()
    for tool in visible_tools:
        name = tool.spec.name
        if name in seen_names:
            continue
        seen_names.add(name)
        deduped.append(tool)
    return deduped
