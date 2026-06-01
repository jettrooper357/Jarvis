"""Decision Log tools — expose ``DecisionLogStore`` to agents."""

from __future__ import annotations

from typing import Any

from openjarvis.assistant.decisions.store import Decision, DecisionLogStore
from openjarvis.core.registry import ToolRegistry
from openjarvis.core.types import ToolResult
from openjarvis.tools._stubs import BaseTool, ToolSpec


def _decision_store() -> DecisionLogStore:
    from openjarvis.core.events import get_event_bus

    return DecisionLogStore(bus=get_event_bus())


def _format(d: Decision) -> str:
    parts = [
        f"id={d.id}",
        f"statement={d.statement}",
        f"status={d.status}",
        f"decided_by={d.decided_by}",
    ]
    if d.approved_by:
        parts.append(f"approved_by={d.approved_by}")
    return " | ".join(parts)


@ToolRegistry.register("decision_record")
class DecisionRecordTool(BaseTool):
    """Record a decision or approval in the decision log."""

    tool_id = "decision_record"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="decision_record",
            description=(
                "Record a decision (and who approved it) in the durable decision "
                "log. Link it to a project/task and the source when known."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "statement": {
                        "type": "string",
                        "description": "The decision made.",
                    },
                    "rationale": {
                        "type": "string",
                        "description": "User-safe reason (no hidden reasoning).",
                    },
                    "decided_by": {"type": "string"},
                    "approved_by": {"type": "string"},
                    "source_ref": {"type": "string"},
                    "linked_task_id": {"type": "string"},
                    "linked_project_id": {"type": "string"},
                    "supersedes": {
                        "type": "string",
                        "description": "Prior decision id this replaces.",
                    },
                },
                "required": ["statement"],
            },
            category="assistant",
            requires_confirmation=True,
        )

    def execute(self, **params: Any) -> ToolResult:
        try:
            d = _decision_store().record(
                statement=str(params.get("statement", "")),
                rationale=str(params.get("rationale", "") or ""),
                decided_by=str(params.get("decided_by", "") or ""),
                approved_by=str(params.get("approved_by", "") or ""),
                source_ref=str(params.get("source_ref", "") or ""),
                linked_task_id=str(params.get("linked_task_id", "") or ""),
                linked_project_id=str(params.get("linked_project_id", "") or ""),
                supersedes=str(params.get("supersedes", "") or ""),
            )
        except ValueError as exc:
            return ToolResult(
                tool_name=self.spec.name, success=False, content=str(exc)
            )
        return ToolResult(
            tool_name=self.spec.name,
            success=True,
            content=f"Recorded decision: {_format(d)}",
            metadata={"decision_id": d.id},
        )


@ToolRegistry.register("decision_list")
class DecisionListTool(BaseTool):
    """List recorded decisions, optionally filtered."""

    tool_id = "decision_list"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="decision_list",
            description=(
                "List decisions. Filter by linked_project_id, linked_task_id, "
                "or status."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "linked_project_id": {"type": "string"},
                    "linked_task_id": {"type": "string"},
                    "status": {
                        "type": "string",
                        "enum": ["active", "superseded", "revoked"],
                    },
                },
            },
            category="assistant",
            requires_confirmation=False,
        )

    def execute(self, **params: Any) -> ToolResult:
        try:
            items = _decision_store().list(
                linked_project_id=params.get("linked_project_id") or None,
                linked_task_id=params.get("linked_task_id") or None,
                status=params.get("status") or None,
            )
        except ValueError as exc:
            return ToolResult(
                tool_name=self.spec.name, success=False, content=str(exc)
            )
        if not items:
            return ToolResult(
                tool_name=self.spec.name, success=True, content="No decisions."
            )
        body = "\n".join(_format(d) for d in items)
        return ToolResult(
            tool_name=self.spec.name,
            success=True,
            content=body,
            metadata={"count": len(items)},
        )
