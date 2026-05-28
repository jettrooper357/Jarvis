"""Chief Orchestrator action envelope.

The Chief Orchestrator emits one structured action per turn instead of a
free-form tool call. This module defines the action dataclass, its
payload sub-types, and a lenient parser that extracts the action from a
model response.

The action vocabulary is intentionally narrow in this first slice:

- ``complete`` — terminal; return the ``final_report`` to the user.
- ``delegate`` — dispatch one or more delegations and loop.
- ``ask_user`` — terminal; surface the ``followup_question`` to the user.
- ``fail``    — terminal; surface ``reason`` as an error.

``execute_direct``, ``run_workflow``, and ``enqueue_background`` from the
full design doc are intentionally out of scope here; if the model emits
``execute_direct`` the parser folds it into ``complete``.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class ActionType(str, Enum):
    COMPLETE = "complete"
    DELEGATE = "delegate"
    EXECUTE_DIRECT = "execute_direct"
    ASK_USER = "ask_user"
    FAIL = "fail"


_ACTION_ALIASES: Dict[str, ActionType] = {}

_VALID_REPORT_STATUSES = {"completed", "partial", "failed"}
_VALID_RESPONSE_TYPES = {
    "free_text",
    "single_choice",
    "multi_choice",
    "approval",
    "credential",
    "file",
}


class ParseError(ValueError):
    """Raised when a model response cannot be parsed into an action."""


@dataclass(slots=True)
class ToolCallSpec:
    """A tool call the chief wants to execute directly (no delegation).

    ``arguments`` is the JSON string the underlying tool expects. The
    parser accepts either a JSON object (which it re-serializes) or a
    pre-serialized string -- whichever the model emits.
    """

    name: str
    arguments: str


@dataclass(slots=True)
class Delegation:
    agent_name_or_id: str
    message: str
    acceptance_criteria: List[str] = field(default_factory=list)
    budget_max_turns: Optional[int] = None
    depends_on: List[str] = field(default_factory=list)
    task_id: Optional[str] = None
    # Least-privilege override: when set, the child can only call tools
    # whose names appear here. None means "child uses its configured set".
    tools_allowed: Optional[List[str]] = None


@dataclass(slots=True)
class FollowupQuestion:
    question: str
    reason: str
    expected_response_type: str = "free_text"
    options: List[str] = field(default_factory=list)


@dataclass(slots=True)
class FinalReport:
    status: str
    summary: str
    artifacts: List[str] = field(default_factory=list)
    followups_needed: List[str] = field(default_factory=list)
    evidence: List[str] = field(default_factory=list)


@dataclass(slots=True)
class OrchestratorAction:
    action: ActionType
    reason: str = ""
    delegations: List[Delegation] = field(default_factory=list)
    tool_calls: List[ToolCallSpec] = field(default_factory=list)
    followup_question: Optional[FollowupQuestion] = None
    final_report: Optional[FinalReport] = None


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

_FENCED_JSON_RE = re.compile(
    r"```(?:json)?\s*(\{.*?\})\s*```",
    re.DOTALL | re.IGNORECASE,
)


def _extract_json_object(text: str) -> Dict[str, Any]:
    """Pull the first JSON object out of *text*.

    Tries the whole string, then a fenced ```json``` block, then the
    first balanced ``{...}`` substring.
    """
    stripped = (text or "").strip()
    if not stripped:
        raise ParseError("empty response")

    try:
        loaded = json.loads(stripped)
        if isinstance(loaded, dict):
            return loaded
    except json.JSONDecodeError:
        pass

    fenced = _FENCED_JSON_RE.search(stripped)
    if fenced:
        try:
            loaded = json.loads(fenced.group(1))
            if isinstance(loaded, dict):
                return loaded
        except json.JSONDecodeError as exc:
            raise ParseError(f"fenced JSON block was invalid: {exc}") from exc

    start = stripped.find("{")
    if start == -1:
        raise ParseError("no JSON object found in response")
    depth = 0
    in_string = False
    escape = False
    for idx in range(start, len(stripped)):
        ch = stripped[idx]
        if escape:
            escape = False
            continue
        if ch == "\\":
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                candidate = stripped[start : idx + 1]
                try:
                    loaded = json.loads(candidate)
                    if isinstance(loaded, dict):
                        return loaded
                    raise ParseError("top-level JSON value was not an object")
                except json.JSONDecodeError as exc:
                    raise ParseError(f"JSON object was invalid: {exc}") from exc
    raise ParseError("unterminated JSON object in response")


def _parse_delegation(raw: Any, index: int) -> Delegation:
    if not isinstance(raw, dict):
        raise ParseError(f"delegations[{index}] must be an object")
    agent = str(raw.get("agent_name_or_id", "") or raw.get("agent", "")).strip()
    message = str(raw.get("message", "") or raw.get("task", "")).strip()
    if not agent:
        raise ParseError(f"delegations[{index}].agent_name_or_id is required")
    if not message:
        raise ParseError(f"delegations[{index}].message is required")
    criteria_raw = raw.get("acceptance_criteria") or []
    if not isinstance(criteria_raw, list):
        raise ParseError(f"delegations[{index}].acceptance_criteria must be a list")
    criteria = [str(c).strip() for c in criteria_raw if str(c).strip()]
    budget = raw.get("budget_max_turns")
    budget_val: Optional[int]
    if budget is None:
        budget_val = None
    else:
        try:
            budget_val = int(budget)
        except (TypeError, ValueError) as exc:
            raise ParseError(
                f"delegations[{index}].budget_max_turns must be an integer"
            ) from exc
        if budget_val < 1:
            raise ParseError(
                f"delegations[{index}].budget_max_turns must be >= 1"
            )
    depends_raw = raw.get("depends_on") or []
    if not isinstance(depends_raw, list):
        raise ParseError(f"delegations[{index}].depends_on must be a list")
    depends = [str(d).strip() for d in depends_raw if str(d).strip()]
    task_id = raw.get("task_id")
    tools_raw = raw.get("tools_allowed")
    tools_allowed: Optional[List[str]]
    if tools_raw is None:
        tools_allowed = None
    elif isinstance(tools_raw, list):
        tools_allowed = [str(t).strip() for t in tools_raw if str(t).strip()]
        if not tools_allowed:
            # An empty list is a meaningful policy: "no tools at all". Keep
            # it as an empty list rather than collapsing to None.
            tools_allowed = []
    else:
        raise ParseError(
            f"delegations[{index}].tools_allowed must be a list or null"
        )
    return Delegation(
        agent_name_or_id=agent,
        message=message,
        acceptance_criteria=criteria,
        budget_max_turns=budget_val,
        depends_on=depends,
        task_id=str(task_id).strip() if task_id else None,
        tools_allowed=tools_allowed,
    )


def _parse_tool_call(raw: Any, index: int) -> ToolCallSpec:
    if not isinstance(raw, dict):
        raise ParseError(f"tool_calls[{index}] must be an object")
    name = str(raw.get("name", "")).strip()
    if not name:
        raise ParseError(f"tool_calls[{index}].name is required")
    args = raw.get("arguments")
    if args is None:
        args_str = "{}"
    elif isinstance(args, str):
        # Trust the string -- the chief may have already JSON-encoded
        # complex shapes the parser shouldn't second-guess.
        args_str = args
    elif isinstance(args, (dict, list)):
        args_str = json.dumps(args)
    else:
        raise ParseError(
            f"tool_calls[{index}].arguments must be an object, list, or "
            f"JSON string"
        )
    return ToolCallSpec(name=name, arguments=args_str)


def _parse_followup(raw: Any) -> FollowupQuestion:
    if not isinstance(raw, dict):
        raise ParseError("followup_question must be an object")
    question = str(raw.get("question", "")).strip()
    reason = str(raw.get("reason", "")).strip()
    if not question:
        raise ParseError("followup_question.question is required")
    if not reason:
        raise ParseError("followup_question.reason is required")
    expected = str(
        raw.get("expected_response_type") or "free_text"
    ).strip().lower()
    if expected not in _VALID_RESPONSE_TYPES:
        raise ParseError(
            f"followup_question.expected_response_type must be one of "
            f"{sorted(_VALID_RESPONSE_TYPES)}"
        )
    options_raw = raw.get("options") or []
    if not isinstance(options_raw, list):
        raise ParseError("followup_question.options must be a list")
    options = [str(o).strip() for o in options_raw if str(o).strip()]
    return FollowupQuestion(
        question=question,
        reason=reason,
        expected_response_type=expected,
        options=options,
    )


def _parse_final_report(raw: Any) -> FinalReport:
    if not isinstance(raw, dict):
        raise ParseError("final_report must be an object")
    status = str(raw.get("status", "")).strip().lower()
    if status not in _VALID_REPORT_STATUSES:
        raise ParseError(
            f"final_report.status must be one of {sorted(_VALID_REPORT_STATUSES)}"
        )
    summary = str(raw.get("summary", "")).strip()
    if not summary:
        raise ParseError("final_report.summary is required")
    artifacts = [str(a).strip() for a in (raw.get("artifacts") or []) if str(a).strip()]
    followups = [
        str(f).strip() for f in (raw.get("followups_needed") or []) if str(f).strip()
    ]
    evidence = [str(e).strip() for e in (raw.get("evidence") or []) if str(e).strip()]
    return FinalReport(
        status=status,
        summary=summary,
        artifacts=artifacts,
        followups_needed=followups,
        evidence=evidence,
    )


def _repair_openai_tool_call_shape(obj: Dict[str, Any]) -> Dict[str, Any]:
    """Detect an OpenAI-shaped tool call and rewrite it as execute_direct.

    Models trained on the OpenAI function-calling protocol (gpt-4o-mini,
    most cloud-via-OpenAI shims) systematically emit one of these shapes
    instead of the chief's bespoke action envelope:

        {"name": "X", "arguments": {...}}
        {"function": {"name": "X", "arguments": "..."}}
        {"tool_calls": [{"function": {"name": "X", "arguments": "..."}}, ...]}
        {"tool_calls": [{"name": "X", "arguments": {...}}, ...]}

    Repairing on parse rather than retrying lets the chief act on the
    first turn instead of looping until max_turns, which today produces
    a 100+ second "No response was generated" failure. This is a narrow
    backstop; the full fix is the function_calling orchestrator mode
    proposed in docs/CHANGE_IMPACT_NOTICES/chief-function-calling-mode.md.
    """
    if obj.get("action"):
        return obj
    tool_calls: List[Dict[str, Any]] = []
    raw_tool_calls = obj.get("tool_calls")
    if isinstance(raw_tool_calls, list) and raw_tool_calls:
        for tc in raw_tool_calls:
            if not isinstance(tc, dict):
                continue
            fn = tc.get("function") if isinstance(tc.get("function"), dict) else tc
            name = str(fn.get("name", "")).strip()
            args = fn.get("arguments")
            if name:
                tool_calls.append({
                    "name": name,
                    "arguments": args if args is not None else {},
                })
    elif isinstance(obj.get("function"), dict):
        fn = obj["function"]
        name = str(fn.get("name", "")).strip()
        if name:
            tool_calls.append({"name": name, "arguments": fn.get("arguments", {})})
    elif obj.get("name") and "arguments" in obj:
        name = str(obj["name"]).strip()
        if name:
            tool_calls.append({"name": name, "arguments": obj.get("arguments", {})})
    if not tool_calls:
        return obj
    return {
        "action": "execute_direct",
        "reason": (
            "repaired from OpenAI tool-call shape: "
            + ", ".join(tc["name"] for tc in tool_calls)
        ),
        "tool_calls": tool_calls,
    }


def parse_action(text: str) -> OrchestratorAction:
    """Parse a model response into an :class:`OrchestratorAction`.

    Raises :class:`ParseError` if the response is missing required fields
    or carries an unknown action value.
    """
    obj = _extract_json_object(text)
    obj = _repair_openai_tool_call_shape(obj)

    action_raw = str(obj.get("action", "")).strip().lower()
    if not action_raw:
        raise ParseError("action is required")
    if action_raw in _ACTION_ALIASES:
        action = _ACTION_ALIASES[action_raw]
    else:
        try:
            action = ActionType(action_raw)
        except ValueError as exc:
            valid = sorted(a.value for a in ActionType)
            raise ParseError(
                f"unknown action {action_raw!r}; expected one of {valid}"
            ) from exc

    reason = str(obj.get("reason", "")).strip()

    # Parse and validate only the payload field that matches the chosen
    # action. Models often include extra fields (e.g. a placeholder
    # final_report alongside a delegate action); ignore them rather than
    # fail the parse, matching the doc's "only include fields that apply
    # to the chosen action" rule.
    delegations: List[Delegation] = []
    tool_calls_out: List[ToolCallSpec] = []
    followup: Optional[FollowupQuestion] = None
    final_report: Optional[FinalReport] = None

    if action is ActionType.COMPLETE:
        if obj.get("final_report") is None:
            raise ParseError("action=complete requires final_report")
        final_report = _parse_final_report(obj["final_report"])
    elif action is ActionType.DELEGATE:
        raw_delegations = obj.get("delegations") or []
        if not isinstance(raw_delegations, list) or not raw_delegations:
            raise ParseError("action=delegate requires at least one delegation")
        for idx, raw in enumerate(raw_delegations):
            delegations.append(_parse_delegation(raw, idx))
    elif action is ActionType.EXECUTE_DIRECT:
        raw_tool_calls = obj.get("tool_calls") or []
        if not isinstance(raw_tool_calls, list) or not raw_tool_calls:
            raise ParseError(
                "action=execute_direct requires at least one tool_calls entry"
            )
        for idx, raw in enumerate(raw_tool_calls):
            tool_calls_out.append(_parse_tool_call(raw, idx))
    elif action is ActionType.ASK_USER:
        if obj.get("followup_question") is None:
            raise ParseError("action=ask_user requires followup_question")
        followup = _parse_followup(obj["followup_question"])
    elif action is ActionType.FAIL:
        if not reason:
            raise ParseError("action=fail requires a non-empty reason")

    return OrchestratorAction(
        action=action,
        reason=reason,
        delegations=delegations,
        tool_calls=tool_calls_out,
        followup_question=followup,
        final_report=final_report,
    )


# ---------------------------------------------------------------------------
# Delegation message packaging
# ---------------------------------------------------------------------------


def build_delegation_message(delegation: Delegation) -> str:
    """Render a Delegation into the text payload sent to the child agent.

    The child agents in this slice are still text-in / text-out (no envelope),
    so we serialize the contract fields into a clearly labelled prompt
    rather than a JSON object. We separate the *instruction* from the
    *acceptance criteria* with explicit headers so a tool-using
    subordinate (which would otherwise paste the whole user message as a
    tool argument -- the bug behind mangled task titles like "release a
    new song called X. Acceptance criteria:- Task is created...") can
    parse the goal cleanly.
    """
    goal = delegation.message.strip()
    parts: List[str] = [
        "You have been delegated the following task by the Chief "
        "Orchestrator. Complete it using the tools available to you. "
        "Do NOT paste this whole instruction into a tool argument -- "
        "extract just the relevant fields (e.g. the project task title "
        "is the SUBJECT of the request, not the full sentence).",
        f"GOAL:\n{goal}",
    ]
    if delegation.acceptance_criteria:
        bullets = "\n".join(f"- {c}" for c in delegation.acceptance_criteria)
        parts.append(f"ACCEPTANCE CRITERIA:\n{bullets}")
    if delegation.budget_max_turns is not None:
        parts.append(
            f"BUDGET: complete this in at most {delegation.budget_max_turns} turns."
        )
    parts.append(
        "When you finish, reply with a short confirmation of what you "
        "did (e.g. \"Created task 'X' in project Y, start <date>, due "
        "<date>.\") -- the chief will synthesize the final answer to "
        "the user."
    )
    return "\n\n".join(parts)


__all__ = [
    "ActionType",
    "Delegation",
    "FinalReport",
    "FollowupQuestion",
    "OrchestratorAction",
    "ParseError",
    "ToolCallSpec",
    "build_delegation_message",
    "parse_action",
]
