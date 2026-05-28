"""Chief meta-tool: pause the chief and ask the user for input.

Used by the function-calling chief (``orchestrator_mode == "function_calling"``)
to reach the same pause/checkpoint behavior the legacy structured-JSON
chief got from ``action = "ask_user"``. The tool returns a ``ToolResult``
whose ``metadata`` carries the marker ``chief_pause = True`` plus the
question payload; the orchestrator's function-calling loop watches for
that marker, builds a checkpoint identical to the legacy chief shape,
and returns. The runtime then writes the checkpoint via
``ManagedAgentRuntime._maybe_checkpoint_chief`` exactly as before, so
``/chief-pending`` and ``/chief-resume`` keep working unchanged.

See ``docs/CHANGE_IMPACT_NOTICES/chief-function-calling-mode.md``.
"""

from __future__ import annotations

from typing import Any, List, Optional

from openjarvis.core.registry import ToolRegistry
from openjarvis.core.types import ToolResult
from openjarvis.tools._stubs import BaseTool, ToolSpec

_VALID_RESPONSE_TYPES = {
    "free_text",
    "single_choice",
    "multi_choice",
    "approval",
    "credential",
    "file",
}


@ToolRegistry.register("chief_ask_user")
class ChiefAskUserTool(BaseTool):
    # Constructor tolerates the ``context=`` kwarg the capabilities
    # builder passes for AUTO_COLLABORATION_TOOLS members so the tool
    # can sit in that auto-inject list without a special case.
    def __init__(self, context: Optional[Any] = None) -> None:
        super().__init__()
        self._context = context

    """Pause the chief and present a question to the user.

    The chief calls this when it cannot proceed without input. The
    function-calling loop returns immediately after dispatch; the
    runtime persists a checkpoint, sets the agent's status to
    ``input_required`` (or ``auth_required`` for credentials), and the
    UI surfaces the question via ``GET /v1/managed-agents/{id}/chief-pending``.
    """

    tool_id = "chief_ask_user"
    is_local = True

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="chief_ask_user",
            description=(
                "Pause and ask the user a single concrete question. Use "
                "only when you genuinely cannot proceed without input. "
                "Provide a clear ``question`` and the ``reason`` you need "
                "the answer. Optionally constrain ``options`` and "
                "``expected_response_type`` to one of free_text, "
                "single_choice, multi_choice, approval, credential, file."
            ),
            parameters={
                "type": "object",
                "required": ["question"],
                "properties": {
                    "question": {
                        "type": "string",
                        "description": (
                            "The user-facing question (one sentence "
                            "preferred)."
                        ),
                    },
                    "reason": {
                        "type": "string",
                        "description": (
                            "Why this answer is required before continuing."
                        ),
                    },
                    "expected_response_type": {
                        "type": "string",
                        "enum": sorted(_VALID_RESPONSE_TYPES),
                        "description": (
                            "Hint for the UI; defaults to free_text."
                        ),
                    },
                    "options": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "Choices for single_choice / multi_choice / "
                            "approval."
                        ),
                    },
                },
            },
            category="interaction",
            required_capabilities=[],
        )

    def execute(self, **params: Any) -> ToolResult:
        question = str(params.get("question", "") or "").strip()
        if not question:
            return ToolResult(
                tool_name="chief_ask_user",
                content="chief_ask_user requires a non-empty 'question'.",
                success=False,
            )
        reason = str(params.get("reason", "") or "").strip()
        rtype = str(
            params.get("expected_response_type", "free_text") or "free_text"
        ).strip().lower()
        if rtype not in _VALID_RESPONSE_TYPES:
            rtype = "free_text"
        raw_options = params.get("options")
        options: List[str] = []
        if isinstance(raw_options, list):
            for opt in raw_options:
                if isinstance(opt, str) and opt.strip():
                    options.append(opt.strip())
        rendered = question
        if reason:
            rendered = f"{rendered}\n\n(Why: {reason})"
        if options:
            options_block = "\n".join(f"- {o}" for o in options)
            rendered = f"{rendered}\n\nOptions:\n{options_block}"
        return ToolResult(
            tool_name="chief_ask_user",
            content=rendered,
            success=True,
            metadata={
                "chief_pause": True,
                "question": {
                    "question": question,
                    "reason": reason,
                    "expected_response_type": rtype,
                    "options": options,
                },
            },
        )


__all__ = ["ChiefAskUserTool"]
