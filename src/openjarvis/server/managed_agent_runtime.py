"""Synchronous managed-agent runtime used by channel dispatch and delegation."""

from __future__ import annotations

import contextvars
import json
import logging
import re
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, Iterator, List, Optional, Sequence

from openjarvis.agents.capabilities import (
    build_agent_tool_instances,
)
from openjarvis.agents.capabilities import (
    effective_agent_tool_names as _effective_capability_tool_names,
)
from openjarvis.core.events import EventType
from openjarvis.core.types import Message, Role, ToolCall, ToolResult
from openjarvis.tools._stubs import ToolExecutor

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ManagedAgentExecutionContext:
    """Runtime state exposed to delegation-aware tools via a context var."""

    runtime: "ManagedAgentRuntime"
    manager: Any
    engine: Any
    current_agent_id: str
    parent_agent_id: str = ""
    visited_agent_ids: tuple[str, ...] = ()
    # Trace lineage so delegation builds a single tree:
    #   current_trace_id is THIS run's own id (the parent's perspective);
    #   run_id groups every trace from one user request together.
    current_trace_id: Optional[str] = None
    run_id: Optional[str] = None


_execution_context: contextvars.ContextVar[ManagedAgentExecutionContext | None] = (
    contextvars.ContextVar("openjarvis_managed_agent_execution", default=None)
)

# Phase 2G — active per-task session id for the current run. Empty string
# means "general session" (today's behaviour). Set by ``run()`` from its
# ``task_session_id`` argument when worker session isolation is enabled.
_active_task_session_id: contextvars.ContextVar[str] = contextvars.ContextVar(
    "openjarvis_active_task_session_id", default=""
)


def _current_active_session_id() -> Optional[str]:
    """Return the active per-task session id, or ``None`` if unset."""
    value = _active_task_session_id.get()
    return value or None


def _worker_session_isolation_enabled() -> bool:
    """Phase 2G — lazy read of the worker-session-isolation feature flag.

    Mirrors ``openjarvis.agents.manager._worker_session_isolation_enabled``
    so the runtime can decide whether to set the active session id without
    a circular import.
    """
    try:
        from openjarvis.core.config import load_config

        return bool(load_config().worker_session_isolation.enabled)
    except Exception:
        return False


_SHORTCUT_REGISTRY_SINGLETON: Any = None
_SHORTCUT_SEEDED: bool = False


def _get_shortcut_registry(bus: Any) -> Any:
    """Return a process-wide :class:`ShortcutRegistry`, seeding it once.

    Returns ``None`` when shortcuts are disabled or the subsystem cannot
    be imported. The registry is shared across chief construction calls
    so cache invalidation works across both run paths.
    """
    global _SHORTCUT_REGISTRY_SINGLETON, _SHORTCUT_SEEDED
    try:
        from openjarvis.core.config import load_config

        cfg = load_config()
        if not getattr(cfg, "shortcuts", None) or not cfg.shortcuts.enabled:
            return None
    except Exception:
        return None

    if _SHORTCUT_REGISTRY_SINGLETON is None:
        try:
            from openjarvis.shortcuts.registry import ShortcutRegistry

            _SHORTCUT_REGISTRY_SINGLETON = ShortcutRegistry(bus=bus)
        except Exception:
            return None

    if not _SHORTCUT_SEEDED:
        try:
            if cfg.shortcuts.seed_builtin_rules_on_first_run:
                from openjarvis.shortcuts.seed import ensure_seeded

                ensure_seeded(_SHORTCUT_REGISTRY_SINGLETON)
        except Exception:
            pass
        _SHORTCUT_SEEDED = True

    return _SHORTCUT_REGISTRY_SINGLETON


def _build_shortcut_hook(engine: Any, model: str, bus: Any) -> Any:
    """Return a ``pre_turn_hook`` callable, or ``None`` when disabled."""
    registry = _get_shortcut_registry(bus)
    if registry is None:
        return None
    try:
        from openjarvis.core.config import load_config
        from openjarvis.shortcuts import try_shortcut

        cfg = load_config()
        global_post_model = (cfg.shortcuts.default_post_processor_model or "").strip()
    except Exception:
        return None

    post_model = global_post_model or model

    def _hook(user_message: str) -> Any:
        return try_shortcut(
            user_message,
            registry=registry,
            post_engine=engine,
            post_model=post_model,
            bus=bus,
        )

    return _hook


def _chief_function_calling_enabled_for(agent_record: Dict[str, Any]) -> bool:
    """True when this chief should run in OpenAI function-calling mode.

    Requires BOTH the global ``[chief_function_calling].enabled`` flag
    AND the per-agent ``config.orchestrator_mode == "function_calling"``
    opt-in. Either missing falls back to the legacy structured-JSON
    chief mode. See
    ``docs/CHANGE_IMPACT_NOTICES/chief-function-calling-mode.md``.
    """
    config = agent_record.get("config", {}) or {}
    if (
        str(config.get("orchestrator_mode", "") or "").strip().lower()
        != "function_calling"
    ):
        return False
    try:
        from openjarvis.core.config import load_config

        return bool(load_config().chief_function_calling.enabled)
    except Exception:
        return False


def get_managed_agent_context() -> ManagedAgentExecutionContext | None:
    """Return the current managed-agent tool execution context, if any."""
    return _execution_context.get()


@contextmanager
def use_managed_agent_context(
    context: ManagedAgentExecutionContext,
) -> Iterator[ManagedAgentExecutionContext]:
    """Bind managed-agent runtime state for tool execution."""
    token = _execution_context.set(context)
    try:
        yield context
    finally:
        _execution_context.reset(token)


def _tool_call_name(raw: Dict[str, Any]) -> str:
    function = raw.get("function")
    if isinstance(function, dict):
        return str(function.get("name", ""))
    return str(raw.get("name", ""))


def _tool_call_args(raw: Dict[str, Any]) -> str:
    function = raw.get("function")
    if isinstance(function, dict):
        return str(function.get("arguments", ""))
    return str(raw.get("arguments", ""))


def _response_content(result: Any) -> str:
    if isinstance(result, dict):
        return str(result.get("content", "") or "")
    return str(result or "")


def _effective_tool_names(agent_record: Dict[str, Any]) -> List[str]:
    return _effective_capability_tool_names(agent_record)


def _should_enable_knowledge(agent_record: Dict[str, Any]) -> bool:
    from openjarvis.agents.capabilities import should_enable_agent_knowledge

    return should_enable_agent_knowledge(agent_record)


def _role_guidance(agent_record: Dict[str, Any]) -> str:
    role = str(agent_record.get("org_role", "") or "").strip()
    # No early return for a missing role: every agent gets baseline triage
    # rules via the generic default at the end of this function.
    role_key = role.casefold()
    is_chief = (
        "chief orchestrator" in role_key
        or "chief executive officer" in role_key
        or role_key == "ceo"
    )
    if is_chief:
        return (
            "Use your own capabilities FIRST:\n"
            "- You have connected data sources, skills, and presets. Use "
            "them to answer directly. Query your knowledge with "
            "knowledge_search (it covers your connected data sources — "
            "e.g. News/RSS, Hacker News, email, calendar, drive) and run "
            "any skill/preset configured for you.\n"
            "- NEVER claim you 'do not have access' to news, current "
            "events, or any topic without first calling knowledge_search. "
            "If a relevant data source or skill is configured for you, you "
            "DO have access — use it and return the result.\n"
            "- Being the coordinator does not stop you answering "
            "directly. Delegation is a last resort, not the default.\n"
            "\n"
            "Request triage — classify BEFORE acting:\n"
            "- First decide what the request actually needs.\n"
            "- If you can answer it directly (your data sources, skills, "
            "or presets), just do that and reply. Do NOT create a "
            "project or task for questions, lookups, quick chats, or a "
            "single skill/preset job — return the answer itself.\n"
            "- Treat it as project work ONLY when the user explicitly asks "
            "to create/start/track a project, or it is a genuine "
            "multi-step initiative that needs delegation and tracking.\n"
            "\n"
            "When (and only when) it is project work:\n"
            "- You are a top-level coordinator. Project creation is not a "
            "delegated task — call project_create first.\n"
            "- Use project_create_task to create trackable project "
            "tasks/subtasks before assigning agent work.\n"
            "- If no dates are supplied, create the task anyway; the "
            "system defaults start_date to today and due_date to tomorrow.\n"
            "- For project/task setup and tracking work, assign execution "
            "to the Workflow Manager or Project Manager after the project "
            "task exists; do not keep that work on Chief unless no manager "
            "agent exists.\n"
            "- Use managed_agent_directory to discover available agents by "
            "role, then assign execution tasks to the best matching "
            "subordinate with managed_agent_assign_task and the relevant "
            "project_task_id.\n"
            "- Match work to the right role: information, news, research, "
            "and lookup requests go to an Information Officer/CIO — never "
            "to a project or workflow manager. Project/workflow managers "
            "own project setup and tracking, not information retrieval.\n"
            "- If no suitable subordinate exists, state the missing role "
            "clearly and keep the project/task record updated yourself."
        )
    if "project manager" in role_key or "workflow manager" in role_key:
        return (
            "Use your own capabilities FIRST:\n"
            "- Use your connected data sources (via knowledge_search), "
            "skills, and presets to answer directly. Never claim you lack "
            "access to a topic without first checking knowledge_search "
            "when a relevant data source or skill is configured for you.\n"
            "\n"
            "Request triage — classify BEFORE acting:\n"
            "- If you can answer directly or via a skill/preset, just "
            "reply. Do NOT create a project or task for questions, quick "
            "chats, or a single skill/preset job.\n"
            "- Only when the user explicitly asks for a project, or it is "
            "a genuine multi-step initiative:\n"
            "  - Use project_create for new projects.\n"
            "  - Use project_create_task for trackable tasks and "
            "subtasks.\n"
            "  - If no dates are supplied, create the task anyway; the "
            "system defaults start_date to today and due_date to tomorrow.\n"
            "  - Assign agent work only after a project task exists, "
            "passing its project_task_id into managed_agent_assign_task.\n"
            "\n"
            "CRITICAL — task creation discipline:\n"
            "- Create EXACTLY ONE project_create_task per delegated "
            "request. Do NOT call project_create_task a second time in the "
            "same turn to 'clean up' a prior attempt — the first call "
            "succeeded or the result tells you why it didn't. If a delegate "
            "message contains one goal, that is one task.\n"
            "- The task TITLE is the concise SUBJECT of the request "
            "(e.g. \"Raise One for the Old Guard\"), NOT the full "
            "instruction. Never paste a delegation goal, an "
            "\"ACCEPTANCE CRITERIA:\" block, or the entire user message "
            "into the title field. If the request is "
            "\"release a new song called X\", the title is \"Release new "
            "song: X\" or simply \"X\" — not the full sentence.\n"
            "- Only create multiple tasks in one turn when the user "
            "explicitly lists multiple items (e.g. \"create three tasks: "
            "A, B, and C\")."
        )
    is_information_officer = (
        "information officer" in role_key
        or role_key == "cio"
        or "research" in role_key
        or "analyst" in role_key
        or "intelligence" in role_key
    )
    if is_information_officer:
        return (
            "You are the information/research authority. Answer "
            "information, news, research, monitoring, and lookup requests "
            "DIRECTLY and yourself.\n"
            "- knowledge_search is your primary tool — it covers your "
            "connected data sources (News/RSS, Hacker News, email, "
            "calendar, drive). Always call it before saying you lack "
            "access to any topic.\n"
            "- Synthesize the retrieved results into a concise, sourced "
            "answer. Do NOT paste the raw search output back — summarize "
            "the key points and include links where available.\n"
            "\n"
            "Request triage — classify BEFORE acting:\n"
            "- News, current events, lookups, and research questions are "
            "YOUR job: answer directly via knowledge_search/skills. NEVER "
            "create a project or task for these, and never delegate them "
            "to a project or workflow manager.\n"
            "- Treat it as project work ONLY when the user explicitly "
            "asks to create/start/track a project, or it is a genuine "
            "multi-step initiative; only then use project_create / "
            "project_create_task."
        )
    # Generic default — every other (or unspecified) role still gets
    # baseline triage so no agent routes a simple question into a project.
    return (
        "Use your own capabilities FIRST:\n"
        "- You have connected data sources, skills, and presets. Use them "
        "to answer directly. Query your knowledge with knowledge_search "
        "(it covers your connected data sources — e.g. News/RSS, Hacker "
        "News, email, calendar, drive) and run any skill or preset "
        "configured for you.\n"
        "- NEVER claim you 'do not have access' to news, current events, "
        "or any topic without first calling knowledge_search. If a "
        "relevant data source or skill is configured for you, you DO have "
        "access — use it and return the result.\n"
        "\n"
        "Request triage — classify BEFORE acting:\n"
        "- Decide what the request actually needs, then act once. If you "
        "can answer it directly (your data sources, skills, or presets), "
        "just do that and reply.\n"
        "- Do NOT create a project or task for questions, lookups, quick "
        "chats, or a single skill/preset job — return the answer itself. "
        "This is an interactive chat: prefer a direct answer over routing "
        "or delegation.\n"
        "- Treat it as project work ONLY when the user explicitly asks "
        "to create/start/track a project, or it is a genuine multi-step "
        "initiative; only then use project_create / project_create_task."
    )


def _today_anchor() -> str:
    """One-line "today is X" anchor for every managed-agent system prompt.

    Models without a current-date prior (e.g. gpt-4o-mini, whose training
    cuts off in 2024) will invent dates when asked to default to "today".
    Anchoring this in the system prompt is the cheapest reliable fix.
    """
    today = datetime.now().date()
    tomorrow = today + timedelta(days=1)
    return (
        f"Today is {today.isoformat()} (use this for any 'today / now / "
        f"soon' reasoning). If a project task or milestone needs a "
        f"start_date and none was supplied, use {today.isoformat()}; for "
        f"due_date / end_date use {tomorrow.isoformat()}. Never invent a "
        "year from your training data -- always use the value above."
    )


def _build_managed_system_prompt(agent_record: Dict[str, Any]) -> str:
    config = agent_record.get("config", {}) or {}
    parts: List[str] = []
    # The today-anchor goes FIRST so the date is the first thing the
    # model sees and stays salient through long prompts.
    parts.append(_today_anchor())
    system_prompt = str(config.get("system_prompt", "") or "").strip()
    instruction = str(config.get("instruction", "") or "").strip()
    personality = str(config.get("personality", "") or "").strip()
    if system_prompt:
        parts.append(system_prompt)
    if instruction and instruction != system_prompt:
        parts.append(f"Agent instruction:\n{instruction}")
    if personality:
        parts.append(
            "Personality (voice / tone / mannerisms — shape how you reply, "
            "without altering the task or any rules above):\n" + personality
        )
    role_guidance = _role_guidance(agent_record)
    if role_guidance:
        parts.append(role_guidance)
    return "\n\n".join(parts)


_AGENT_TASK_COMPLETION_TOOLS = {
    "project_create",
    "project_create_task",
}


def _tool_calls_completed_agent_task(
    tool_calls: Optional[List[Dict[str, Any]]],
) -> bool:
    if not tool_calls:
        return False
    return any(
        call.get("tool") in _AGENT_TASK_COMPLETION_TOOLS
        and call.get("success", False)
        for call in tool_calls
    )


_PROJECT_TASK_VERBS = ("add", "create", "make", "open", "log", "record")
_PROJECT_MATCH_STOPWORDS = {
    "a",
    "an",
    "and",
    "for",
    "project",
    "projects",
    "the",
    "to",
}


def _text_tokens(value: str) -> List[str]:
    return [
        token
        for token in re.findall(r"[a-z0-9]+", str(value or "").casefold())
        if token and token not in _PROJECT_MATCH_STOPWORDS
    ]


def _text_key(value: str) -> str:
    return " ".join(_text_tokens(value))


def _default_chat_project_task_dates() -> Dict[str, str]:
    start = datetime.now().date()
    return {
        "start_date": start.isoformat(),
        "due_date": (start + timedelta(days=1)).isoformat(),
    }


_OUTLINE_TASK_RE = re.compile(
    r"^\s*(?:task|sub[\s\-_]?task)\s*:",
    re.IGNORECASE | re.MULTILINE,
)
_OUTLINE_CATEGORY_RE = re.compile(
    r"^\s*cat[ea]?gor(?:y|ies)\s*:",
    re.IGNORECASE | re.MULTILINE,
)
_OUTLINE_NUMBERED_RE = re.compile(r"^\s*\d+\.\d+\s+\S", re.MULTILINE)


def _looks_like_bulk_outline(text: str) -> bool:
    """True when the user's message is a multi-level project outline.

    Triggers when there are at least 3 ``Task:`` / ``SubTask:`` lines, or
    at least 3 numbered ``N.M`` task lines. Either grammar is what
    ``project_import_outline`` accepts.
    """
    if not text:
        return False
    label_hits = len(_OUTLINE_TASK_RE.findall(text))
    if label_hits >= 3 and _OUTLINE_CATEGORY_RE.search(text):
        return True
    if label_hits >= 5:
        return True
    if len(_OUTLINE_NUMBERED_RE.findall(text)) >= 3:
        return True
    return False


def _prepend_outline_routing_hint(text: str) -> str:
    """Steer the chief toward project_import_outline for bulk outlines.

    gpt-4o-mini and similar small models ignore tool-description hints
    when the user payload is huge. A short, explicit instruction at the
    top of the user content reliably wins.
    """
    if not _looks_like_bulk_outline(text):
        return text
    hint = (
        "[ROUTING HINT — system-injected]\n"
        "The message below is a multi-level project outline with many "
        "Category / Task / SubTask items. You MUST handle it with a "
        "single project_import_outline tool call that passes the FULL "
        "outline verbatim in the `outline` parameter, plus `project_name` "
        "(extracted from the user's intro line) and `create_if_missing=true`. "
        "Do NOT call project_create_task in a loop for each subtask — "
        "that exhausts the turn budget and produces no reply.\n"
        "---\n"
    )
    return hint + text


_OUTLINE_PROJECT_NAME_RES = (
    # "...add this to the Veridex Project ..." / "in the Iron Saints project"
    re.compile(
        r"\b(?:to|into|in|on|under|for)\s+(?:the\s+)?"
        r"(?P<name>[A-Za-z0-9][A-Za-z0-9 &'._-]*?)\s+projects?\b",
        re.IGNORECASE,
    ),
    # "...project called Veridex" / "project named Veridex"
    re.compile(
        r"\bprojects?\s+(?:called|named|titled)\s+"
        r"(?P<name>[A-Za-z0-9][A-Za-z0-9 &'._-]*)",
        re.IGNORECASE,
    ),
)
_OUTLINE_NAME_STOPWORDS = {"this", "the", "a", "an", "new", "that", "it"}


def _extract_outline_project_name(text: str) -> str:
    """Pull the target project name from a bulk-outline intro line.

    Only the head of the message is scanned: users name the destination
    project in the intro ("add this to the Veridex Project ..."), so this
    avoids false matches against Category/Task lines deeper in the body.
    Returns "" when no clear project name is present.
    """
    head = str(text or "")[:400]
    for pattern in _OUTLINE_PROJECT_NAME_RES:
        match = pattern.search(head)
        if match:
            name = match.group("name").strip(" .,:;-\"'")
            if name and name.casefold() not in _OUTLINE_NAME_STOPWORDS:
                return name
    return ""


_MULTI_TASK_RE = re.compile(
    r"\b("
    r"(?:create|add|make|open)\s+(?:two|three|four|five|\d+)\s+tasks?"
    r"|tasks?\s*:\s*[A-Za-z0-9]"
    r"|multiple\s+tasks?"
    r"|several\s+tasks?"
    r")\b",
    re.IGNORECASE,
)


def _user_asked_for_multiple_tasks(text: str) -> bool:
    """Detect an explicit signal that the user wants more than one task.

    Used to gate the "one project_create_task per turn" cap. The default
    is single-task: the cap only lifts when the message has an obvious
    multi-item phrasing.
    """
    if not text:
        return False
    return bool(_MULTI_TASK_RE.search(str(text)))


def _clean_project_task_title(title: str) -> str:
    text = str(title or "").strip()
    return re.sub(
        r"\s+(?:to|in|on|under)\s+(?:the\s+)?"
        r"[A-Za-z0-9 &'._-]+?\s+project\.?$",
        "",
        text,
        flags=re.IGNORECASE,
    ).strip(" .,:;-\"'") or text


class ManagedAgentRuntime:
    """Run managed agents synchronously with tool-calling and delegation."""

    def __init__(
        self,
        manager: Any,
        engine: Any,
        *,
        bus: Any = None,
        default_model: str = "",
        trace_store: Any = None,
        credential_scrubber: Any = None,
        credential_vault: Any = None,
        approval_store: Any = None,
        approval_gating: Any = None,
    ) -> None:
        from openjarvis.security.credential_scrubber import CredentialScrubber
        from openjarvis.security.credential_vault import CredentialVault

        self._manager = manager
        self._engine = engine
        self._bus = bus
        self._default_model = default_model
        self._trace_store = trace_store
        self._scrubber = credential_scrubber or CredentialScrubber()
        self._vault = credential_vault or CredentialVault()
        # Phase 2D enforcement — the approval gate is a transparent
        # no-op unless an ApprovalStore is wired AND
        # approval_gating.enabled is set. ``approval_gating`` may be
        # injected (tests); otherwise it is read lazily from config.
        self._approval_store = approval_store
        self._approval_gating = approval_gating

    def _scrub_tool_calls(
        self,
        tool_calls: Optional[List[Dict[str, Any]]],
        run_id: Optional[str],
    ) -> Optional[List[Dict[str, Any]]]:
        """Apply the credential scrubber to ``arguments``/``result`` fields."""
        if not tool_calls or not run_id:
            return tool_calls
        scrub = self._scrubber.scrub
        out: List[Dict[str, Any]] = []
        for call in tool_calls:
            new_call = dict(call)
            if "arguments" in new_call:
                new_call["arguments"] = scrub(
                    new_call.get("arguments", ""), run_id
                )
            if "result" in new_call:
                new_call["result"] = scrub(new_call.get("result", ""), run_id)
            out.append(new_call)
        return out

    # -- approval gating (Phase 2D enforcement) ---------------------

    def _approval_gating_config(self) -> Any:
        """Lazily resolve the ``approval_gating`` config block."""
        if self._approval_gating is None:
            try:
                from openjarvis.core.config import load_config

                self._approval_gating = load_config().approval_gating
            except Exception:
                from openjarvis.core.config import ApprovalGatingConfig

                self._approval_gating = ApprovalGatingConfig()
        return self._approval_gating

    def _owning_open_task_id(self, agent_id: str) -> Optional[str]:
        """Best-effort: newest non-terminal task owned by ``agent_id``."""
        terminal = {"completed", "failed", "cancelled", "done"}
        try:
            for task in self._manager.list_tasks(agent_id):
                if str(task.get("status", "") or "").lower() not in terminal:
                    return str(task.get("id"))
        except Exception:
            logger.exception("Failed to resolve owning task for %s", agent_id)
        return None

    def _approval_gate(
        self,
        agent_record: Dict[str, Any],
        tool_call: ToolCall,
    ) -> Optional[ToolResult]:
        """Consult the approval policy before a managed-agent tool runs.

        Returns ``None`` to allow the call (today's behaviour), or a
        ``ToolResult`` to short-circuit it (denied / awaiting approval).
        A transparent no-op unless an ``ApprovalStore`` is wired, the
        ``approval_gating`` flag is on, and the tool is listed in the
        owning agent's ``requires_approval_tools`` capability axis.
        """
        store = self._approval_store
        if store is None:
            return None
        cfg = self._approval_gating_config()
        if not getattr(cfg, "enabled", False):
            return None
        config = agent_record.get("config", {}) or {}
        gated = config.get("requires_approval_tools") or []
        if isinstance(gated, str):
            gated = [gated]
        gated_set = {str(t).strip() for t in gated if str(t).strip()}
        if tool_call.name not in gated_set:
            return None

        from openjarvis.agents.approvals import args_hash as _args_hash

        agent_id = str(agent_record.get("id", "") or "")
        a_hash = _args_hash(tool_call.arguments or "")
        try:
            actionable = store.find_actionable(
                agent_id, tool_call.name, a_hash
            )
        except Exception:
            logger.exception(
                "Approval gate lookup failed for %s", tool_call.name
            )
            actionable = None

        if actionable is not None and actionable.state == "granted":
            try:
                store.mark_consumed(actionable.id)
            except Exception:
                logger.exception(
                    "Failed to consume approval %s", actionable.id
                )
            return None

        if actionable is not None and actionable.state == "denied":
            reason = (
                actionable.reason
                or "A human reviewer denied this action."
            )
            return ToolResult(
                tool_name=tool_call.name,
                content=f"Approval denied: {reason}",
                success=False,
                metadata={
                    "approval": {"state": "denied", "id": actionable.id}
                },
            )

        return self._block_pending_approval(
            agent_record, tool_call, a_hash
        )

    def _block_pending_approval(
        self,
        agent_record: Dict[str, Any],
        tool_call: ToolCall,
        a_hash: str,
    ) -> ToolResult:
        """Create a pending approval row and return a blocking result."""
        store = self._approval_store
        agent_id = str(agent_record.get("id", "") or "")
        try:
            parsed = (
                json.loads(tool_call.arguments)
                if tool_call.arguments
                else {}
            )
            args_obj = parsed if isinstance(parsed, dict) else {"_value": parsed}
        except Exception:
            args_obj = {"_raw": str(tool_call.arguments or "")}

        task_id = self._owning_open_task_id(agent_id)
        summary = (
            f"{agent_record.get('name', agent_id)} requested approval "
            f"to run {tool_call.name}"
        )
        req = None
        try:
            req = store.request(
                agent_id=agent_id,
                capability=tool_call.name,
                args=args_obj,
                task_id=task_id,
                summary=summary,
                requested_by=agent_id,
                args_hash=a_hash,
            )
        except Exception:
            logger.exception(
                "Failed to create approval request for %s", tool_call.name
            )

        if task_id:
            try:
                self._manager.update_task(
                    task_id,
                    status="awaiting_approval",
                    requires_approval=True,
                )
            except Exception:
                logger.exception(
                    "Failed to mark task %s awaiting_approval", task_id
                )

        req_id = req.id if req is not None else "pending"
        return ToolResult(
            tool_name=tool_call.name,
            content=(
                f"Awaiting human approval — request {req_id}. This action "
                f"({tool_call.name}) is paused until a human grants it. "
                "Do not retry; report to the user that the action is "
                "blocked pending approval."
            ),
            success=False,
            metadata={"approval": {"state": "pending", "id": req_id}},
        )

    def run(
        self,
        agent_id: str,
        user_content: str,
        *,
        parent_agent_id: str = "",
        visited_agent_ids: Optional[Sequence[str]] = None,
        parent_trace_id: Optional[str] = None,
        run_id: Optional[str] = None,
        tools_allowed: Optional[Sequence[str]] = None,
        task_session_id: Optional[str] = None,
    ) -> str:
        """Run the agent inside its project workspace sandbox, if any.

        When the agent has a linked project task whose project has a
        ``working_folder`` configured, filesystem and shell tools called
        during this run are sandboxed to that folder.
        """
        from openjarvis.projects.workspace import use_workspace

        workspace = self._active_project_workspace(agent_id)
        with use_workspace(workspace):
            return self._run_locked(
                agent_id,
                user_content,
                parent_agent_id=parent_agent_id,
                visited_agent_ids=visited_agent_ids,
                parent_trace_id=parent_trace_id,
                run_id=run_id,
                tools_allowed=tools_allowed,
                task_session_id=task_session_id,
            )

    def _run_locked(
        self,
        agent_id: str,
        user_content: str,
        *,
        parent_agent_id: str = "",
        visited_agent_ids: Optional[Sequence[str]] = None,
        parent_trace_id: Optional[str] = None,
        run_id: Optional[str] = None,
        tools_allowed: Optional[Sequence[str]] = None,
        task_session_id: Optional[str] = None,
    ) -> str:
        # Phase 2G — scope the active per-task session id for this call.
        # Only takes effect when worker_session_isolation is enabled AND a
        # non-empty session id is supplied; otherwise the contextvar is
        # cleared so a prior tagged run in the same context can't bleed in.
        if task_session_id and _worker_session_isolation_enabled():
            _active_task_session_id.set(str(task_session_id))
        else:
            _active_task_session_id.set("")
        agent_record = self._manager.get_agent(agent_id)
        if agent_record is None:
            raise KeyError(f"Agent {agent_id!r} not found")
        # The "all open tasks are future-scheduled" gate is for scheduler
        # ticks and channel messages -- contexts where the runtime is
        # opportunistically firing the agent. When a chief explicitly
        # delegates (parent_agent_id set), the subordinate is being told
        # to do work *now*, regardless of its existing task backlog.
        # Gating delegations here silently swallows the chief's request
        # and produces the "Cannot complete" message users have seen.
        if (
            not parent_agent_id
            and hasattr(self._manager, "has_open_linked_task")
            and self._manager.has_open_linked_task(agent_id)
            and hasattr(self._manager, "has_runnable_task")
            and not self._manager.has_runnable_task(agent_id)
        ):
            raise ValueError(
                "Agent has linked work, but every open task is scheduled "
                "for a future start date/time."
            )

        mode = "delegated" if parent_agent_id else "channel"
        started_at = time.time()
        agent_name = str(agent_record.get("name", agent_id))
        # Trace lineage: every run gets a fresh trace_id; the root run
        # uses its own trace_id as the run_id so children share it.
        from openjarvis.core.types import _trace_id as _new_trace_id

        effective_trace_id = _new_trace_id()
        effective_run_id = run_id or effective_trace_id

        # Apply the credential scrubber to *inbound* user content. A
        # delegated subordinate sees whatever message the chief sent;
        # if the chief embedded a credential the parent ran registered
        # against this run_id, replace it before it lands in the
        # persistent agent_messages log.
        user_content = self._scrubber.scrub(user_content, effective_run_id)
        if self._bus is not None:
            try:
                self._bus.publish(
                    EventType.AGENT_TICK_START,
                    {
                        "agent_id": agent_id,
                        "agent_name": agent_name,
                        "parent_agent_id": parent_agent_id or "",
                        "mode": mode,
                    },
                )
            except Exception:
                logger.exception("Failed to publish AGENT_TICK_START for %s", agent_id)
        message = self._manager.send_message(
            agent_id,
            user_content,
            mode=mode,
            session_id=_current_active_session_id(),
        )
        message_id = message["id"]
        if self._bus is not None:
            try:
                self._bus.publish(
                    EventType.AGENT_MESSAGE_RECEIVED,
                    {
                        "agent_id": agent_id,
                        "agent_name": agent_name,
                        "parent_agent_id": parent_agent_id or "",
                        "message_id": message_id,
                        "mode": mode,
                    },
                )
            except Exception:
                logger.exception(
                    "Failed to publish AGENT_MESSAGE_RECEIVED for %s",
                    agent_id,
                )
        self._project_writeback(agent_record, phase="start", summary=user_content)
        response_text = ""
        tool_calls: Optional[List[Dict[str, Any]]] = None
        project_task_ids_to_enqueue: List[str] = []
        had_error = False
        try:
            response_text, tool_calls = self._run_turn(
                agent_record=agent_record,
                user_content=user_content,
                message_id=message_id,
                parent_agent_id=parent_agent_id,
                visited_agent_ids=visited_agent_ids or (),
                trace_id=effective_trace_id,
                run_id=effective_run_id,
                parent_trace_id=parent_trace_id,
                tools_allowed=tools_allowed,
            )
        except Exception as exc:
            logger.exception("Managed agent turn failed for %s", agent_id)
            response_text = f"Sorry, the agent failed: {exc}"
            had_error = True
        finally:
            try:
                self._manager.mark_message_delivered(message_id)
            except Exception:
                logger.exception("Failed to mark message delivered for %s", agent_id)
        if not had_error:
            materialized = self._maybe_materialize_project_task_request(
                agent_record=agent_record,
                user_content=user_content,
                response_text=response_text,
                tool_calls=tool_calls,
            )
            if materialized is not None:
                tool_calls = list(tool_calls or [])
                tool_calls.append(materialized)
                metadata = materialized.get("metadata")
                if isinstance(metadata, dict):
                    project_task_id = str(
                        metadata.get("project_task_id") or ""
                    )
                    if project_task_id:
                        project_task_ids_to_enqueue.append(project_task_id)
                result_text = str(materialized.get("result", "") or "")
                if result_text and result_text not in response_text:
                    response_text = (
                        f"{response_text}\n\n{result_text}"
                        if response_text
                        else result_text
                    )
        safe_response = self._scrubber.scrub(response_text, effective_run_id)
        safe_tool_calls = self._scrub_tool_calls(tool_calls, effective_run_id)
        self._manager.store_agent_response(
            agent_id,
            safe_response,
            tool_calls=safe_tool_calls or None,
            session_id=_current_active_session_id(),
        )
        if (
            not had_error
            and _tool_calls_completed_agent_task(tool_calls)
        ):
            self._complete_linked_agent_task(
                agent_id,
                note="Completed by successful project setup tool execution.",
            )
            project_task_ids_to_enqueue.extend(
                self._project_task_ids_from_tool_calls(tool_calls)
            )
        self._project_writeback(
            agent_record,
            phase="finish",
            summary=response_text,
            error=had_error,
        )
        if not had_error:
            for project_task_id in dict.fromkeys(project_task_ids_to_enqueue):
                self._enqueue_project_task_for_agent(
                    agent_record=agent_record,
                    project_task_id=project_task_id,
                    description=user_content,
                )
        if self._bus is not None:
            try:
                event_type = (
                    EventType.AGENT_TICK_ERROR
                    if had_error
                    else EventType.AGENT_TICK_END
                )
                payload = {
                    "agent_id": agent_id,
                    "agent_name": agent_name,
                    "parent_agent_id": parent_agent_id or "",
                    "duration": time.time() - started_at,
                    "status": "error" if had_error else "ok",
                    "summary": response_text[:240],
                }
                if had_error:
                    payload["error"] = response_text[:240]
                self._bus.publish(event_type, payload)
            except Exception:
                logger.exception("Failed to publish completion event for %s", agent_id)
        if self._trace_store is not None:
            try:
                from openjarvis.core.types import Trace

                trace = Trace(
                    trace_id=effective_trace_id,
                    parent_trace_id=parent_trace_id,
                    run_id=effective_run_id,
                    query=user_content,
                    agent=agent_id,
                    model=str(
                        (agent_record.get("config") or {}).get("model", "")
                        or self._default_model
                    ),
                    engine=getattr(self._engine, "engine_id", ""),
                    result=response_text[:4000],
                    outcome="error" if had_error else "success",
                    started_at=started_at,
                    ended_at=time.time(),
                    total_latency_seconds=time.time() - started_at,
                    metadata={
                        "agent_name": agent_name,
                        "mode": mode,
                        "parent_agent_id": parent_agent_id,
                        "tool_calls": tool_calls or [],
                    },
                )
                self._trace_store.save(trace)
            except Exception:
                logger.exception(
                    "Failed to save trace for managed-agent run %s", agent_id
                )
        return response_text

    # ── Project-task writeback (Mission Control) ──────────────────

    def _active_project_workspace(self, agent_id: str) -> str:
        """Return the working folder of the agent's active project, or ''.

        Looks up the agent's most relevant linked project task, follows
        the project reference, and returns its ``working_folder``. Used
        to scope filesystem/shell tools to a per-project sandbox.
        """
        try:
            link = self._linked_project_task(agent_id)
        except Exception:
            return ""
        if not link or not link.get("project_task_id"):
            return ""
        try:
            ps = self._manager._project_store()
            ptask = ps.get_task(str(link["project_task_id"]))
            if not ptask:
                return ""
            project = ps.get_project(str(ptask.get("project_id") or ""))
            if not project:
                return ""
            return str(project.get("working_folder") or "")
        except Exception:
            return ""

    def _linked_project_task(self, agent_id: str) -> Optional[Dict[str, Any]]:
        """The agent's most relevant linked agent-task (active > recent)."""
        try:
            if hasattr(self._manager, "list_runnable_tasks"):
                tasks = self._manager.list_runnable_tasks(agent_id)
            else:
                tasks = self._manager.list_tasks(agent_id)
        except Exception:
            return None
        for status in ("active", "pending"):
            for t in tasks:
                if t.get("status") == status and t.get("project_task_id"):
                    return t
        for t in tasks:
            if t.get("project_task_id"):
                return t
        return None

    def _complete_linked_agent_task(self, agent_id: str, *, note: str) -> None:
        """Mark the current linked agent-task complete after deterministic work.

        The model can always call managed_agent_update_task itself. This
        fallback covers deterministic one-shot work such as project_create,
        where the tool result proves the assigned setup task is done.
        """
        try:
            task = self._linked_project_task(agent_id)
            if not task or task.get("status") == "completed":
                return
            progress = dict(task.get("progress") or {})
            progress["note"] = note
            self._manager.update_task(
                task["id"],
                status="completed",
                progress=progress,
            )
        except Exception:
            logger.exception("Failed to complete linked task for %s", agent_id)

    def _project_writeback(
        self,
        agent_record: Dict[str, Any],
        *,
        phase: str,
        summary: str = "",
        error: bool = False,
    ) -> None:
        """Mirror a run into its linked project task (best-effort).

        Role-gated via :mod:`openjarvis.projects.authz`: a note is added
        when allowed (all tiers), and status/percent is changed only when
        the agent may update the task (manager any; worker its own task).
        On success of a leaf task with no subtasks owned by the agent the
        task is completed; otherwise it is only nudged to In Progress so
        we never over-claim rolled-up progress. Never raises into the run.
        """
        try:
            link = self._linked_project_task(agent_record["id"])
            if not link or not link.get("project_task_id"):
                return
            ptid = str(link["project_task_id"])
            ps = self._manager._project_store()
            ptask = ps.get_task(ptid)
            if ptask is None:
                return

            from openjarvis.projects import authz

            agent_name = str(agent_record.get("name") or agent_record["id"])
            if authz.can(agent_record, "note.add", ptask):
                if phase == "start":
                    content = (
                        f"Agent '{agent_name}' started a run: "
                        f"{summary[:200]}"
                    )
                    ntype = "Agent"
                elif error:
                    content = (
                        f"Agent '{agent_name}' run failed: {summary[:300]}"
                    )
                    ntype = "Blocker"
                else:
                    content = (
                        f"Agent '{agent_name}' completed a run: "
                        f"{summary[:300]}"
                    )
                    ntype = "Agent"
                ps.add_note(
                    ptid, author=agent_name, content=content, type=ntype
                )

            if not authz.can(agent_record, "task.update", ptask):
                return
            updates: Dict[str, Any] = {}
            current = str(ptask.get("status") or "")
            nudge = ("", "Backlog", "Planning", "To Do")
            if phase == "start":
                if current in nudge:
                    updates["status"] = "In Progress"
            elif error:
                updates["status"] = "Blocked"
            else:
                subtasks = [
                    t
                    for t in ps.list_tasks(ptask["project_id"])
                    if t.get("parent_task_id") == ptid
                ]
                if not subtasks:
                    updates["status"] = "Done"
                    updates["percent_complete"] = 100
                elif current in nudge:
                    updates["status"] = "In Progress"
            if updates:
                ps.update_task(ptid, **updates)
        except Exception:
            logger.exception(
                "Project writeback (%s) failed for agent %s",
                phase,
                agent_record.get("id"),
            )

    def _maybe_import_bulk_outline(
        self,
        *,
        agent_record: Dict[str, Any],
        user_content: str,
        collected_tool_calls: List[Dict[str, Any]],
    ) -> Optional[str]:
        """Deterministically import a pasted multi-level outline.

        A large Category/Task/SubTask paste cannot be echoed back by the
        model as a ``project_import_outline`` argument within the output
        token budget, so the chat would burn its turns and return no reply
        (the "No response was generated" symptom). When the inbound message
        is a bulk outline AND the agent may use ``project_import_outline``,
        import it server-side with no model round-trip, record a synthetic
        tool call for the audit log / live event sidebar, and return the
        summary so the Chief delivers the result to the user.

        Returns ``None`` to fall through to the normal model turn (message
        is not an outline, the agent lacks the capability, the target
        project name is unclear, or the import itself failed).
        """
        if not _looks_like_bulk_outline(user_content):
            return None
        if "project_import_outline" not in _effective_tool_names(agent_record):
            return None
        project_name = _extract_outline_project_name(user_content)
        if not project_name:
            return None
        try:
            from openjarvis.tools.project_import_outline import import_outline

            store = self._manager._project_store()
            outcome = import_outline(
                store,
                outline=user_content,
                project_name=project_name,
                create_if_missing=True,
            )
        except Exception:
            logger.exception(
                "Deterministic bulk-outline import failed for agent %s",
                agent_record.get("id"),
            )
            return None

        if not outcome.get("success"):
            logger.warning(
                "Bulk-outline import did not succeed for agent %s: %s",
                agent_record.get("id"),
                outcome.get("content"),
            )
            return None

        collected_tool_calls.append(
            {
                "tool": "project_import_outline",
                "arguments": json.dumps(
                    {
                        "project_name": project_name,
                        "create_if_missing": True,
                        "outline": user_content,
                    }
                ),
                "result": outcome["content"],
                "success": True,
                "latency": 0.0,
                "metadata": outcome.get("metadata") or {},
            }
        )
        return outcome["content"]

    def _maybe_materialize_project_task_request(
        self,
        *,
        agent_record: Dict[str, Any],
        user_content: str,
        response_text: str,
        tool_calls: Optional[List[Dict[str, Any]]],
    ) -> Optional[Dict[str, Any]]:
        """Create the project task when the model acknowledged but skipped it.

        This is intentionally narrow: it only handles explicit user requests
        to add/create a task in a named project, and only for agents that are
        already allowed to use ``project_create_task``.
        """
        # A bulk outline is handled by the deterministic import fast path,
        # never as a single materialized task -- bail so we don't create a
        # stray top-level task alongside the imported breakdown.
        if _looks_like_bulk_outline(user_content):
            return None
        if "project_create_task" not in _effective_tool_names(agent_record):
            return None
        if any(
            call.get("tool") == "project_create_task"
            and call.get("success", False)
            for call in tool_calls or []
        ):
            return None
        # If this agent successfully delegated the work, the subordinate
        # already handled it (created the task in its own run). The
        # chief's tool_calls only contain managed_agent_delegate, not the
        # inner project_create_task -- so without this check we would
        # materialize a *second* task at the chief level for the same
        # user request. This is the root of the "two tasks not one" bug.
        if any(
            call.get("tool")
            in (
                "managed_agent_delegate",
                "managed_agent_assign_task",
                "managed_agent_message",
            )
            and call.get("success", False)
            for call in tool_calls or []
        ):
            return None

        parsed = self._parse_project_task_request(user_content)
        if parsed is None:
            return None

        try:
            store = self._manager._project_store()
            project = self._match_project(store.list_projects(), parsed["project"])
            if project is None:
                return {
                    "tool": "project_create_task",
                    "arguments": json.dumps(parsed),
                    "result": (
                        "Project task not recorded: no matching project was "
                        f"found for '{parsed['project']}'."
                    ),
                    "success": False,
                    "latency": 0.0,
                }

            title = _clean_project_task_title(parsed["title"])
            existing = self._find_existing_project_task(
                store.list_tasks(project["id"]),
                title,
            )
            if existing is not None:
                return {
                    "tool": "project_create_task",
                    "arguments": json.dumps(parsed),
                    "result": (
                        "Project task already exists: "
                        f"{existing.get('title', title)}."
                    ),
                    "success": True,
                    "latency": 0.0,
                }

            target_agent = self._preferred_worker_for_project_task(agent_record, None)
            agent_name = str(
                (target_agent or agent_record).get("name")
                or agent_record.get("name")
                or agent_record["id"]
            )
            default_dates = _default_chat_project_task_dates()
            task = store.create_task(
                project["id"],
                title=title,
                description=user_content,
                status="In Progress",
                assigned_to=agent_name,
                owner=agent_name,
                priority="Medium",
                start_date=default_dates["start_date"],
                due_date=default_dates["due_date"],
            )
            return {
                "tool": "project_create_task",
                "arguments": json.dumps(
                    {
                        "project_id": project["id"],
                        "title": title,
                        "status": "In Progress",
                        "start_date": default_dates["start_date"],
                        "due_date": default_dates["due_date"],
                    }
                ),
                "result": (
                    "Project task recorded: "
                    f"{task['title']} in {project.get('name', 'project')}."
                ),
                "success": True,
                "latency": 0.0,
                "metadata": {
                    "project_id": task["project_id"],
                    "project_task_id": task["id"],
                },
            }
        except Exception:
            logger.exception(
                "Failed to materialize project task request for agent %s",
                agent_record.get("id"),
            )
            return None

    def _parse_project_task_request(
        self,
        user_content: str,
    ) -> Optional[Dict[str, str]]:
        text = str(user_content or "").strip()
        lowered = text.casefold()
        if "task" not in lowered or "project" not in lowered:
            return None
        if not any(re.search(rf"\b{verb}\b", lowered) for verb in _PROJECT_TASK_VERBS):
            return None

        project_match = re.search(
            r"\b(?:to|in|on|under|for)\s+(?:the\s+)?"
            r"(?P<project>[A-Za-z0-9 &'._-]+?)\s+project\b",
            text,
            flags=re.IGNORECASE,
        )
        if project_match is None:
            project_match = re.search(
                r"\bproject\s+(?:called|named)?\s*"
                r"(?P<project>[A-Za-z0-9 &'._-]+)",
                text,
                flags=re.IGNORECASE,
            )
        if project_match is None:
            return None

        project_name = project_match.group("project").strip(" .,:;-\"'")
        title = self._project_task_title_from_request(text, project_match.end())
        if not project_name or not title:
            return None
        return {"project": project_name, "title": title}

    def _project_task_title_from_request(
        self,
        text: str,
        project_end: int,
    ) -> str:
        song_match = re.search(
            r"\b(?:called|named|titled)\s+['\"]?(?P<title>[^'\"]+?)['\"]?\.?$",
            text,
            flags=re.IGNORECASE,
        )
        if song_match and re.search(
            r"\breleas(?:e|ing)\b.*\bsong\b",
            text,
            flags=re.IGNORECASE,
        ):
            return _clean_project_task_title(song_match.group("title"))

        tail = text[project_end:].strip(" .,:;-")
        tail = re.sub(
            r"^(?:for|to|called|named|titled)\s+",
            "",
            tail,
            flags=re.IGNORECASE,
        ).strip(" .,:;-\"'")
        if tail:
            return _clean_project_task_title(tail[:120])

        generic = re.sub(
            r"\b(?:add|create|make|open|log|record)\b\s+(?:a\s+)?task\b",
            "",
            text,
            flags=re.IGNORECASE,
        ).strip(" .,:;-")
        generic = re.sub(
            r"^(?:called|named|titled)\s+",
            "",
            generic,
            flags=re.IGNORECASE,
        ).strip(" .,:;-\"'")
        return _clean_project_task_title(generic[:120]) or "New Project Task"

    def _match_project(
        self,
        projects: Sequence[Dict[str, Any]],
        requested_name: str,
    ) -> Optional[Dict[str, Any]]:
        requested_key = _text_key(requested_name)
        requested_tokens = set(requested_key.split())
        if not requested_key or not requested_tokens:
            return None

        best_project: Optional[Dict[str, Any]] = None
        best_score = 0
        for project in projects:
            project_key = _text_key(str(project.get("name", "")))
            project_tokens = set(project_key.split())
            if not project_tokens:
                continue
            overlap = requested_tokens & project_tokens
            score = len(overlap) * 10
            if requested_key in project_key or project_key in requested_key:
                score += 100
            if score > best_score:
                best_project = project
                best_score = score

        required_overlap = 1 if len(requested_tokens) == 1 else 2
        if best_project is None:
            return None
        best_tokens = set(_text_key(str(best_project.get("name", ""))).split())
        if len(requested_tokens & best_tokens) < required_overlap:
            return None
        return best_project

    def _find_existing_project_task(
        self,
        tasks: Sequence[Dict[str, Any]],
        title: str,
    ) -> Optional[Dict[str, Any]]:
        title_key = _text_key(title)
        for task in tasks:
            if _text_key(str(task.get("title", ""))) == title_key:
                return task
        return None

    def _project_task_ids_from_tool_calls(
        self,
        tool_calls: Optional[List[Dict[str, Any]]],
    ) -> List[str]:
        ids: List[str] = []
        for call in tool_calls or []:
            if call.get("tool") != "project_create_task" or not call.get("success"):
                continue
            result = str(call.get("result") or "")
            match = re.search(r"\bid=([A-Za-z0-9_-]+)", result)
            if match:
                ids.append(match.group(1))
        return ids

    def _preferred_worker_for_project_task(
        self,
        agent_record: Dict[str, Any],
        project_task: Optional[Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        assigned_to = str((project_task or {}).get("assigned_to") or "").strip()
        if assigned_to:
            exact = next(
                (
                    agent
                    for agent in self._manager.list_agents()
                    if str(agent.get("name", "")).strip().casefold()
                    == assigned_to.casefold()
                ),
                None,
            )
            if exact is not None:
                return exact

        role = str(agent_record.get("org_role", "") or "").casefold()
        name = str(agent_record.get("name", "") or "").casefold()
        is_chief = "chief" in role or "chief" in name
        if not is_chief:
            return agent_record

        workflow = next(
            (
                agent
                for agent in self._manager.list_agents()
                if agent.get("id") != agent_record.get("id")
                and (
                    "workflow manager"
                    in str(agent.get("org_role", "") or agent.get("name", "")).casefold()
                    or "project manager"
                    in str(agent.get("org_role", "") or agent.get("name", "")).casefold()
                )
            ),
            None,
        )
        return workflow or agent_record

    def _enqueue_project_task_for_agent(
        self,
        *,
        agent_record: Dict[str, Any],
        project_task_id: str,
        description: str,
    ) -> None:
        """Create runnable agent work for a chat-created project task."""
        try:
            ptask = self._manager._project_store().get_task(project_task_id)
            target_agent = self._preferred_worker_for_project_task(
                agent_record,
                ptask,
            )
            if target_agent is None:
                return
            agent_id = str(target_agent["id"])
            target_name = str(target_agent.get("name") or agent_id)
            existing = [
                task
                for task in self._manager.list_tasks(agent_id)
                if str(task.get("project_task_id") or "") == project_task_id
                and str(task.get("status") or "") not in ("completed", "failed")
            ]
            if existing:
                return
            project_id = str((ptask or {}).get("project_id") or "") or None
            if ptask is not None and str(ptask.get("assigned_to") or "") != target_name:
                self._manager._project_store().update_task(
                    project_task_id,
                    assigned_to=target_name,
                    owner=target_name,
                )
            self._manager.create_task(
                agent_id,
                description=str((ptask or {}).get("title") or description),
                status="active",
                project_task_id=project_task_id,
                project_id=project_id,
            )
        except Exception:
            logger.exception(
                "Failed to enqueue materialized project task for agent %s",
                agent_record.get("id"),
            )

    def _run_turn(
        self,
        *,
        agent_record: Dict[str, Any],
        user_content: str,
        message_id: str,
        parent_agent_id: str,
        visited_agent_ids: Sequence[str],
        trace_id: Optional[str] = None,
        run_id: Optional[str] = None,
        parent_trace_id: Optional[str] = None,
        tools_allowed: Optional[Sequence[str]] = None,
    ) -> tuple[str, List[Dict[str, Any]]]:
        agent_id = agent_record["id"]
        config = agent_record.get("config", {}) or {}
        model = (
            config.get("model")
            or getattr(self._engine, "_model", "")
            or self._default_model
        )
        if not model:
            raise RuntimeError("No model configured for managed agent runtime")

        execution_context = ManagedAgentExecutionContext(
            runtime=self,
            manager=self._manager,
            engine=self._engine,
            current_agent_id=agent_id,
            parent_agent_id=parent_agent_id,
            visited_agent_ids=tuple(visited_agent_ids),
            current_trace_id=trace_id,
            run_id=run_id,
        )

        orchestrator_mode = str(
            config.get("orchestrator_mode", "") or ""
        ).strip().lower()

        with use_managed_agent_context(execution_context):
            if agent_record.get("agent_type", "") == "deep_research":
                return self._run_deep_research_turn(
                    agent_record=agent_record,
                    user_content=user_content,
                    model=model,
                    execution_context=execution_context,
                    tools_allowed=tools_allowed,
                )
            if orchestrator_mode == "chief":
                return self._run_chief_turn(
                    agent_record=agent_record,
                    user_content=user_content,
                    model=model,
                    execution_context=execution_context,
                    tools_allowed=tools_allowed,
                )
            return self._run_standard_turn(
                agent_record=agent_record,
                user_content=user_content,
                message_id=message_id,
                model=model,
                execution_context=execution_context,
                tools_allowed=tools_allowed,
            )

    def _run_deep_research_turn(
        self,
        *,
        agent_record: Dict[str, Any],
        user_content: str,
        model: str,
        execution_context: ManagedAgentExecutionContext,
        tools_allowed: Optional[Sequence[str]] = None,
    ) -> tuple[str, List[Dict[str, Any]]]:
        from openjarvis.agents.deep_research import DeepResearchAgent

        config = agent_record.get("config", {}) or {}
        tools = build_agent_tool_instances(
            agent_record,
            engine=self._engine,
            model=model,
            bus=self._bus,
            execution_context=execution_context,
            interactive=True,
            confirm_callback=lambda _prompt: True,
            restrict_to_tool_names=tools_allowed,
        )
        collected_tool_calls: List[Dict[str, Any]] = []

        dr_agent = DeepResearchAgent(
            engine=self._engine,
            model=model,
            tools=tools,
            bus=self._bus,
            max_turns=int(config.get("max_turns", 8)),
            temperature=float(config.get("temperature", 0.3)),
            max_tokens=int(config.get("max_tokens", 4096)),
            interactive=True,
            confirm_callback=lambda _prompt: True,
            system_prompt=_build_managed_system_prompt(agent_record),
        )

        original_execute = dr_agent._executor.execute

        def _tracked_execute(tool_call: ToolCall) -> ToolResult:
            gated = self._approval_gate(agent_record, tool_call)
            if gated is not None:
                collected_tool_calls.append(
                    {
                        "tool": tool_call.name,
                        "arguments": tool_call.arguments or "",
                        "result": gated.content or "",
                        "success": bool(gated.success),
                        "latency": 0.0,
                    }
                )
                return gated
            result = original_execute(tool_call)
            collected_tool_calls.append(
                {
                    "tool": tool_call.name,
                    "arguments": tool_call.arguments or "",
                    "result": result.content or "",
                    "success": bool(result.success),
                    "latency": float(result.latency_seconds or 0.0),
                }
            )
            return result

        dr_agent._executor.execute = _tracked_execute
        result = dr_agent.run(user_content)
        return result.content or "No results found.", collected_tool_calls

    def _run_chief_turn(
        self,
        *,
        agent_record: Dict[str, Any],
        user_content: str,
        model: str,
        execution_context: ManagedAgentExecutionContext,
        tools_allowed: Optional[Sequence[str]] = None,
    ) -> tuple[str, List[Dict[str, Any]]]:
        from openjarvis.agents.orchestrator import OrchestratorAgent

        config = agent_record.get("config", {}) or {}

        # Deterministic fast path: a pasted multi-level outline is imported
        # server-side rather than round-tripped through the model (which
        # cannot echo a large outline back within the token budget).
        early_tool_calls: List[Dict[str, Any]] = []
        outline_summary = self._maybe_import_bulk_outline(
            agent_record=agent_record,
            user_content=user_content,
            collected_tool_calls=early_tool_calls,
        )
        if outline_summary is not None:
            return outline_summary, early_tool_calls

        tool_instances = build_agent_tool_instances(
            agent_record,
            engine=self._engine,
            model=model,
            bus=self._bus,
            execution_context=execution_context,
            interactive=True,
            confirm_callback=lambda _prompt: True,
            restrict_to_tool_names=tools_allowed,
        )

        registry = self._build_chief_registry(str(agent_record["id"]))

        collected_tool_calls: List[Dict[str, Any]] = []

        use_function_calling = _chief_function_calling_enabled_for(agent_record)
        chief = OrchestratorAgent(
            engine=self._engine,
            model=model,
            tools=tool_instances,
            bus=self._bus,
            max_turns=int(config.get("max_turns", 6)),
            temperature=float(config.get("temperature", 0.2)),
            max_tokens=int(config.get("max_tokens", 1024)),
            mode="function_calling" if use_function_calling else "chief",
            chief_registry=registry,
            interactive=True,
            confirm_callback=lambda _prompt: True,
            pre_turn_hook=_build_shortcut_hook(self._engine, model, self._bus),
        )

        original_execute = chief._executor.execute
        chief_agent_id = str(agent_record["id"])

        def _tracked_execute(tool_call: ToolCall) -> ToolResult:
            gated = self._approval_gate(agent_record, tool_call)
            if gated is not None:
                collected_tool_calls.append(
                    {
                        "tool": tool_call.name,
                        "arguments": tool_call.arguments or "",
                        "result": gated.content or "",
                        "success": bool(gated.success),
                        "latency": 0.0,
                    }
                )
                return gated
            # Signal to the UI / Mission Control that the chief is
            # parked on a tool call. Best-effort: a failure to update
            # status must not abort the tool execution.
            try:
                self._manager.update_agent(
                    chief_agent_id,
                    status="waiting_on_tool",
                    current_activity=f"tool: {tool_call.name}",
                )
            except Exception:
                logger.exception(
                    "Failed to set waiting_on_tool status for %s",
                    chief_agent_id,
                )
            try:
                result = original_execute(tool_call)
            finally:
                try:
                    self._manager.update_agent(
                        chief_agent_id,
                        status="running",
                        current_activity="",
                    )
                except Exception:
                    logger.exception(
                        "Failed to clear waiting_on_tool status for %s",
                        chief_agent_id,
                    )
            collected_tool_calls.append(
                {
                    "tool": tool_call.name,
                    "arguments": tool_call.arguments or "",
                    "result": result.content or "",
                    "success": bool(result.success),
                    "latency": float(result.latency_seconds or 0.0),
                }
            )
            return result

        chief._executor.execute = _tracked_execute
        result = chief.run(_prepend_outline_routing_hint(user_content))
        self._maybe_checkpoint_chief(
            agent_record=agent_record,
            execution_context=execution_context,
            result=result,
        )
        return result.content or "No results.", collected_tool_calls

    def _build_chief_registry(self, chief_id: str) -> Dict[str, Dict[str, object]]:
        """Direct subordinates first; fall back to all-other-agents."""
        direct: Dict[str, Dict[str, object]] = {}
        others: Dict[str, Dict[str, object]] = {}
        try:
            for other in self._manager.list_agents():
                other_id = str(other.get("id", "") or "")
                if not other_id or other_id == chief_id:
                    continue
                entry: Dict[str, object] = {
                    "name": other.get("name", other_id),
                    "role": str(other.get("org_role", "") or ""),
                    "hint": str(other.get("summary_memory", "") or "")[:120],
                }
                if str(other.get("manager_agent_id", "") or "") == chief_id:
                    direct[other_id] = entry
                else:
                    others[other_id] = entry
        except Exception:
            logger.exception("Failed to build chief registry for %s", chief_id)
        return direct or others

    def _maybe_checkpoint_chief(
        self,
        *,
        agent_record: Dict[str, Any],
        execution_context: ManagedAgentExecutionContext,
        result: Any,
    ) -> None:
        """If the chief paused for user input, persist a resumable checkpoint.

        Status routing depends on what the chief is waiting on:
        ``expected_response_type == "credential"`` -> ``auth_required``
        (UI surfaces a password input and the resume answer is redacted
        in the trace); anything else -> ``input_required``.
        """
        chief_meta = (getattr(result, "metadata", None) or {}).get("chief") or {}
        if chief_meta.get("action") != "ask_user":
            return
        checkpoint = chief_meta.get("checkpoint")
        if not isinstance(checkpoint, dict):
            return
        agent_id = str(agent_record["id"])
        tick_id = (
            str(execution_context.run_id or "")
            or str(execution_context.current_trace_id or "")
            or "chief_pause"
        )
        conversation_state = {"messages": checkpoint.get("messages", [])}
        tool_state = {
            k: v for k, v in checkpoint.items() if k != "messages"
        }
        tool_state["trace_id"] = execution_context.current_trace_id
        tool_state["run_id"] = execution_context.run_id
        question = checkpoint.get("question") or {}
        is_credential = (
            str(question.get("expected_response_type", "") or "").lower()
            == "credential"
        )
        status = "auth_required" if is_credential else "input_required"
        try:
            self._manager.save_checkpoint(
                agent_id,
                tick_id=tick_id,
                conversation_state=conversation_state,
                tool_state=tool_state,
            )
            self._manager.update_agent(agent_id, status=status)
        except Exception:
            logger.exception(
                "Failed to persist chief checkpoint for %s",
                agent_id,
            )

    def resume(self, agent_id: str, user_answer: str) -> str:
        """Resume a chief that previously emitted action=ask_user.

        Loads the latest checkpoint, appends ``user_answer`` to the
        restored conversation, runs the chief's resume entry, and
        persists results. Trace lineage stays in the same ``run_id``.
        """
        from openjarvis.agents.orchestrator import OrchestratorAgent
        from openjarvis.core.types import (
            Message,
            Role,
            ToolCall,
            ToolResult,
            Trace,
            _trace_id,
        )

        agent_record = self._manager.get_agent(agent_id)
        if agent_record is None:
            raise KeyError(f"Agent {agent_id!r} not found")
        checkpoint = self._manager.get_latest_checkpoint(agent_id)
        if checkpoint is None:
            raise ValueError(f"No checkpoint to resume for {agent_id}")

        conv = checkpoint.get("conversation_state") or {}
        tool_state = checkpoint.get("tool_state") or {}

        messages: List[Message] = []
        for raw in conv.get("messages", []):
            try:
                role = Role(raw["role"])
            except Exception:
                role = Role.USER
            msg = Message(
                role=role,
                content=raw.get("content", "") or "",
                name=raw.get("name"),
                tool_call_id=raw.get("tool_call_id"),
            )
            if raw.get("tool_calls"):
                msg.tool_calls = [
                    ToolCall(
                        id=tc["id"],
                        name=tc["name"],
                        arguments=tc["arguments"],
                    )
                    for tc in raw["tool_calls"]
                ]
            messages.append(msg)

        tool_results = [
            ToolResult(
                tool_name=tr.get("tool_name", ""),
                content=tr.get("content", "") or "",
                success=bool(tr.get("success", True)),
            )
            for tr in tool_state.get("tool_results", [])
        ]
        already_delegated = bool(tool_state.get("already_delegated", False))
        turns_so_far = int(tool_state.get("turns", 0) or 0)
        saved_run_id = tool_state.get("run_id")
        saved_trace_id = tool_state.get("trace_id")
        saved_question = tool_state.get("question") or {}
        was_credential = (
            str(saved_question.get("expected_response_type", "") or "").lower()
            == "credential"
        )

        config = agent_record.get("config", {}) or {}
        model = (
            config.get("model")
            or getattr(self._engine, "_model", "")
            or self._default_model
        )
        if not model:
            raise RuntimeError("No model configured for resume")

        started_at = time.time()
        new_trace_id = _trace_id()
        effective_run_id = saved_run_id or new_trace_id

        # Two-pronged credential handling on resume:
        #
        # 1. The vault stores the raw value and hands back an opaque
        #    token. The chief is given the TOKEN as its user_answer, so
        #    its in-memory messages, any checkpoint it produces, any
        #    delegation message it builds, and the inference engine call
        #    itself only ever see the token. Tokens are dereferenced
        #    inside the executor wrapper just before each tool runs.
        # 2. The scrubber is registered with the raw value as defence in
        #    depth: if a tool *result* echoes the credential back
        #    (e.g., an API response that includes the token), it gets
        #    redacted before we persist it.
        #
        # Both are purged in the finally block.
        scrubber_registered = False
        chief_user_answer = user_answer
        if was_credential:
            scrubber_registered = self._scrubber.register(
                effective_run_id, user_answer
            )
            token = self._vault.store(effective_run_id, user_answer)
            if token:
                chief_user_answer = token

        try:
            execution_context = ManagedAgentExecutionContext(
                runtime=self,
                manager=self._manager,
                engine=self._engine,
                current_agent_id=agent_id,
                current_trace_id=new_trace_id,
                run_id=effective_run_id,
            )

            # Persist the user's answer as a channel message so transcripts
            # and Mission Control reflect that an answer arrived. For
            # credential answers, never write the raw value -- agent_messages
            # is a long-lived audit log and would expose the secret to any
            # tool that lists messages. The chief still receives the raw
            # value in-memory below; only the persisted copy is redacted.
            if was_credential:
                message_to_persist = (
                    f"[credential supplied: {len(user_answer)} chars]"
                )
            else:
                message_to_persist = user_answer
            user_msg = self._manager.send_message(
                agent_id,
                message_to_persist,
                mode="channel",
                session_id=_current_active_session_id(),
            )
            message_id = user_msg["id"]

            registry = self._build_chief_registry(agent_id)
            tool_instances = build_agent_tool_instances(
                agent_record,
                engine=self._engine,
                model=model,
                bus=self._bus,
                execution_context=execution_context,
                interactive=True,
                confirm_callback=lambda _prompt: True,
            )

            with use_managed_agent_context(execution_context):
                use_function_calling = _chief_function_calling_enabled_for(
                    agent_record
                )
                chief = OrchestratorAgent(
                    engine=self._engine,
                    model=model,
                    tools=tool_instances,
                    bus=self._bus,
                    max_turns=int(config.get("max_turns", 6)),
                    temperature=float(config.get("temperature", 0.2)),
                    max_tokens=int(config.get("max_tokens", 1024)),
                    mode="function_calling"
                    if use_function_calling
                    else "chief",
                    chief_registry=registry,
                    interactive=True,
                    confirm_callback=lambda _prompt: True,
                    pre_turn_hook=_build_shortcut_hook(
                        self._engine, model, self._bus
                    ),
                )

                # Wrap the chief's executor: dereference vault tokens
                # against this run_id just before the actual tool runs,
                # so the chief itself never holds the raw secret.
                original_execute = chief._executor.execute

                def _dereferencing_execute(tc: ToolCall) -> ToolResult:
                    gated = self._approval_gate(agent_record, tc)
                    if gated is not None:
                        return gated
                    resolved_args = self._vault.resolve(
                        tc.arguments or "", effective_run_id
                    )
                    if resolved_args != (tc.arguments or ""):
                        substituted = ToolCall(
                            id=tc.id,
                            name=tc.name,
                            arguments=resolved_args,
                        )
                    else:
                        substituted = tc
                    try:
                        self._manager.update_agent(
                            agent_id,
                            status="waiting_on_tool",
                            current_activity=f"tool: {tc.name}",
                        )
                    except Exception:
                        logger.exception(
                            "Failed to set waiting_on_tool on resume for %s",
                            agent_id,
                        )
                    try:
                        out = original_execute(substituted)
                    finally:
                        try:
                            self._manager.update_agent(
                                agent_id,
                                status="running",
                                current_activity="",
                            )
                        except Exception:
                            logger.exception(
                                "Failed to clear waiting_on_tool on resume for %s",
                                agent_id,
                            )
                    if out.content:
                        scrubbed = self._scrubber.scrub(
                            out.content, effective_run_id
                        )
                        if scrubbed != out.content:
                            out.content = scrubbed
                    return out

                chief._executor.execute = _dereferencing_execute

                if use_function_calling:
                    result = chief.resume_function_calling(
                        messages=messages,
                        tool_results=tool_results,
                        turns_so_far=turns_so_far,
                        user_answer=chief_user_answer,
                    )
                else:
                    result = chief.resume_chief(
                        messages=messages,
                        tool_results=tool_results,
                        already_delegated=already_delegated,
                        turns_so_far=turns_so_far,
                        user_answer=chief_user_answer,
                    )

            response_text = result.content or ""
            # Scrub before persistence: the chief may have summarized
            # the credential into its response, e.g. echoing what it
            # used. The trace and the agent-response log both get the
            # placeholder version.
            safe_response_text = self._scrubber.scrub(
                response_text, effective_run_id
            )
            self._manager.store_agent_response(
                agent_id,
                safe_response_text,
                session_id=_current_active_session_id(),
            )
            try:
                self._manager.mark_message_delivered(message_id)
            except Exception:
                logger.exception(
                    "Failed to mark resume message delivered for %s", agent_id
                )

            # Trace continuity: parent is the original ask_user trace, run_id
            # stays the same so the whole call tree groups together.
            # For credential answers, never persist the raw value in the
            # trace -- it would leak through TraceStore queries and FTS.
            if self._trace_store is not None:
                try:
                    trace_query = (
                        "[credential redacted]"
                        if was_credential
                        else user_answer
                    )
                    trace = Trace(
                        trace_id=new_trace_id,
                        parent_trace_id=saved_trace_id,
                        run_id=effective_run_id,
                        query=trace_query,
                        agent=agent_id,
                        model=str(model),
                        engine=getattr(self._engine, "engine_id", ""),
                        result=safe_response_text[:4000],
                        outcome="success",
                        started_at=started_at,
                        ended_at=time.time(),
                        total_latency_seconds=time.time() - started_at,
                        metadata={
                            "resume_of": saved_trace_id,
                            "agent_name": agent_record.get("name", ""),
                            "credential_response": was_credential,
                        },
                    )
                    self._trace_store.save(trace)
                except Exception:
                    logger.exception(
                        "Failed to save resume trace for %s", agent_id
                    )

            # If the chief paused again, record the new checkpoint and keep
            # input_required; otherwise return to idle.
            new_meta = (result.metadata or {}).get("chief") or {}
            if (
                new_meta.get("action") == "ask_user"
                and isinstance(new_meta.get("checkpoint"), dict)
            ):
                self._maybe_checkpoint_chief(
                    agent_record=agent_record,
                    execution_context=execution_context,
                    result=result,
                )
            else:
                try:
                    self._manager.update_agent(agent_id, status="idle")
                except Exception:
                    logger.exception(
                        "Failed to clear input_required status for %s",
                        agent_id,
                    )

            return safe_response_text
        finally:
            if scrubber_registered:
                self._scrubber.purge(effective_run_id)
            # Always purge the vault for this run; safe to call even if
            # nothing was stored.
            self._vault.purge(effective_run_id)

    def _run_standard_turn(
        self,
        *,
        agent_record: Dict[str, Any],
        user_content: str,
        message_id: str,
        model: str,
        execution_context: ManagedAgentExecutionContext,
        tools_allowed: Optional[Sequence[str]] = None,
    ) -> tuple[str, List[Dict[str, Any]]]:
        config = agent_record.get("config", {}) or {}

        # Deterministic fast path: import a pasted multi-level outline
        # server-side instead of asking the model to echo it back as a
        # project_import_outline argument (which overflows the token budget).
        early_tool_calls: List[Dict[str, Any]] = []
        outline_summary = self._maybe_import_bulk_outline(
            agent_record=agent_record,
            user_content=user_content,
            collected_tool_calls=early_tool_calls,
        )
        if outline_summary is not None:
            return outline_summary, early_tool_calls

        tool_instances = build_agent_tool_instances(
            agent_record,
            engine=self._engine,
            model=model,
            bus=self._bus,
            execution_context=execution_context,
            interactive=True,
            confirm_callback=lambda _prompt: True,
            restrict_to_tool_names=tools_allowed,
        )
        tool_specs = [tool.to_openai_function() for tool in tool_instances]
        tool_map = {tool.spec.name: tool for tool in tool_instances}

        messages: List[Message] = []
        system_prompt = _build_managed_system_prompt(agent_record)
        if system_prompt:
            messages.append(Message(role=Role.SYSTEM, content=str(system_prompt)))

        # Phase 2G — the history loader honours the active per-task session
        # id. When unset, the manager's flag-gated default applies (untagged-
        # only with isolation on, every-row otherwise).
        history = self._manager.list_messages(
            agent_record["id"],
            limit=50,
            session_id=_current_active_session_id(),
        )
        for item in reversed(history):
            if item["id"] == message_id:
                continue
            if item["direction"] == "user_to_agent":
                messages.append(Message(role=Role.USER, content=item["content"]))
            elif item["direction"] == "agent_to_user":
                messages.append(Message(role=Role.ASSISTANT, content=item["content"]))
        messages.append(
            Message(role=Role.USER, content=_prepend_outline_routing_hint(user_content))
        )

        temperature = float(config.get("temperature", 0.7))
        max_tokens = int(config.get("max_tokens", 1024))
        max_turns = int(config.get("max_turns", 10))
        collected_prefix = ""
        collected_tool_calls: List[Dict[str, Any]] = []
        # Identical-call dedupe: when a model loops and calls the same
        # tool with the same arguments twice in one run, the second
        # call returns the cached result instead of re-executing. This
        # is the safety net behind the "two tasks from one request"
        # bug -- subordinates that re-issue project_create_task get
        # the original result back and move on.
        seen_calls: Dict[tuple, Dict[str, Any]] = {}
        # Semantic cap for project_create_task: one delegated request =
        # one task unless the message explicitly lists multiple items.
        # Models otherwise tend to create two tasks per request -- one
        # with the raw goal pasted as the title, then a clean retry.
        project_task_created = False
        multi_task_allowed = _user_asked_for_multiple_tasks(user_content)

        def _normalize_args(args_str: str) -> str:
            """Canonicalize JSON-ish args so trivially-different forms dedupe."""
            try:
                return json.dumps(json.loads(args_str), sort_keys=True)
            except Exception:
                return (args_str or "").strip()

        for _turn in range(max_turns):
            kwargs: Dict[str, Any] = {
                "model": model,
                "temperature": temperature,
                "max_tokens": max_tokens,
            }
            if tool_specs:
                kwargs["tools"] = tool_specs
            result = self._engine.generate(messages, **kwargs)
            turn_content = _response_content(result)
            tool_calls_raw = (
                result.get("tool_calls", []) if isinstance(result, dict) else []
            )

            if not tool_calls_raw:
                return f"{collected_prefix}{turn_content}", collected_tool_calls

            messages.append(
                Message(
                    role=Role.ASSISTANT,
                    content=turn_content,
                    tool_calls=[
                        ToolCall(
                            id=str(raw.get("id", "")),
                            name=_tool_call_name(raw),
                            arguments=_tool_call_args(raw),
                        )
                        for raw in tool_calls_raw
                    ],
                )
            )

            for raw in tool_calls_raw:
                tool_name = _tool_call_name(raw)
                tool_args = _tool_call_args(raw)
                tool_result_content = f"Tool '{tool_name}' not available"
                tool_success = False
                call_key = (tool_name, _normalize_args(tool_args))
                cached = seen_calls.get(call_key)
                if cached is not None:
                    logger.info(
                        "Managed agent %s tried duplicate tool call "
                        "%s(%s); returning cached result",
                        agent_record.get("id", "?"),
                        tool_name,
                        tool_args[:120],
                    )
                    tool_result_content = (
                        "(duplicate call -- this tool was already run with "
                        "these exact arguments earlier in this turn. "
                        "Original result:)\n" + str(cached.get("content", ""))
                    )
                    tool_success = bool(cached.get("success", True))
                elif (
                    gate_result := self._approval_gate(
                        agent_record,
                        ToolCall(
                            id=str(raw.get("id", "")),
                            name=tool_name,
                            arguments=tool_args,
                        ),
                    )
                ) is not None:
                    # Phase 2D — the tool requires human approval; the
                    # gate created/consulted an approval row. Surface
                    # the blocking/denial result without executing.
                    tool_result_content = gate_result.content or ""
                    tool_success = bool(gate_result.success)
                    seen_calls[call_key] = {
                        "content": tool_result_content,
                        "success": tool_success,
                    }
                elif (
                    tool_name == "project_create_task"
                    and project_task_created
                    and not multi_task_allowed
                ):
                    logger.info(
                        "Managed agent %s tried a second project_create_task "
                        "in one turn without an explicit multi-task signal; "
                        "suppressing to avoid duplicate task creation.",
                        agent_record.get("id", "?"),
                    )
                    tool_result_content = (
                        "(suppressed -- a project_create_task already "
                        "succeeded in this turn. The user asked for one "
                        "task. If you genuinely need a second task, the "
                        "user must list it explicitly (e.g. \"create two "
                        "tasks: A and B\"). Report success using the task "
                        "already created above.)"
                    )
                    tool_success = False
                    seen_calls[call_key] = {
                        "content": tool_result_content,
                        "success": tool_success,
                    }
                else:
                    try:
                        tool = tool_map.get(tool_name)
                        if tool is None:
                            raise KeyError(tool_name)
                        executor = ToolExecutor(
                            tools=[tool],
                            bus=self._bus,
                            interactive=True,
                            confirm_callback=lambda _prompt: True,
                        )
                        result_obj = executor.execute(
                            ToolCall(
                                id=str(raw.get("id", "")),
                                name=tool_name,
                                arguments=tool_args,
                            )
                        )
                        tool_result_content = result_obj.content or ""
                        tool_success = bool(result_obj.success)
                    except Exception as exc:
                        logger.exception(
                            "Managed agent tool execution failed for %s",
                            tool_name,
                        )
                        tool_result_content = (
                            f"Error executing {tool_name}: {exc}"
                        )
                    seen_calls[call_key] = {
                        "content": tool_result_content,
                        "success": tool_success,
                    }
                    if (
                        tool_name == "project_create_task"
                        and tool_success
                    ):
                        project_task_created = True

                collected_tool_calls.append(
                    {
                        "tool": tool_name,
                        "arguments": tool_args,
                        "result": tool_result_content,
                        "success": tool_success,
                        "latency": 0.0,
                    }
                )
                messages.append(
                    Message(
                        role=Role.TOOL,
                        content=tool_result_content,
                        tool_call_id=str(raw.get("id", "")),
                        name=tool_name,
                    )
                )

            collected_prefix += turn_content

        messages.append(
            Message(
                role=Role.USER,
                content=(
                    "Write the best final answer you can from the completed "
                    "tool results. "
                    "Do not call more tools."
                ),
            )
        )
        fallback = self._engine.generate(
            messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return f"{collected_prefix}{_response_content(fallback)}", collected_tool_calls
