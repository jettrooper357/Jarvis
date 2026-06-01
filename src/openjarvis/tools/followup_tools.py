"""Follow-Up Tracker tools — expose ``FollowUpStore`` to agents."""

from __future__ import annotations

from typing import Any

from openjarvis.assistant.followups.store import FollowUp, FollowUpStore
from openjarvis.core.registry import ToolRegistry
from openjarvis.core.types import ToolResult
from openjarvis.tools._stubs import BaseTool, ToolSpec


def _followup_store() -> FollowUpStore:
    from openjarvis.core.events import get_event_bus

    return FollowUpStore(bus=get_event_bus())


def _format(fu: FollowUp) -> str:
    parts = [
        f"id={fu.id}",
        f"summary={fu.summary}",
        f"counterparty={fu.counterparty}",
        f"direction={fu.direction}",
        f"status={fu.status}",
    ]
    return " | ".join(parts)


@ToolRegistry.register("followup_add")
class FollowupAddTool(BaseTool):
    """Create a follow-up the assistant should track."""

    tool_id = "followup_add"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="followup_add",
            description=(
                "Track a follow-up: something you are waiting on from someone "
                "('waiting_on') or owe a reply to ('owe_reply')."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "summary": {
                        "type": "string",
                        "description": "What the follow-up is.",
                    },
                    "counterparty": {
                        "type": "string",
                        "description": "Who it involves.",
                    },
                    "direction": {
                        "type": "string",
                        "enum": ["waiting_on", "owe_reply"],
                        "description": (
                            "waiting_on = they owe you; owe_reply = you owe them."
                        ),
                    },
                    "source_ref": {
                        "type": "string",
                        "description": "Optional channel/message id.",
                    },
                    "linked_task_id": {
                        "type": "string",
                        "description": "Optional project task id.",
                    },
                    "linked_project_id": {
                        "type": "string",
                        "description": "Optional project id.",
                    },
                    "sla_due_at": {
                        "type": "number",
                        "description": "Optional epoch when it becomes stale.",
                    },
                },
                "required": ["summary", "counterparty"],
            },
            category="assistant",
            requires_confirmation=True,
        )

    def execute(self, **params: Any) -> ToolResult:
        try:
            fu = _followup_store().add(
                summary=str(params.get("summary", "")),
                counterparty=str(params.get("counterparty", "")),
                direction=str(params.get("direction", "waiting_on") or "waiting_on"),
                source_ref=str(params.get("source_ref", "") or ""),
                linked_task_id=str(params.get("linked_task_id", "") or ""),
                linked_project_id=str(params.get("linked_project_id", "") or ""),
                sla_due_at=params.get("sla_due_at"),
            )
        except ValueError as exc:
            return ToolResult(
                tool_name=self.spec.name, success=False, content=str(exc)
            )
        return ToolResult(
            tool_name=self.spec.name,
            success=True,
            content=f"Tracking follow-up: {_format(fu)}",
            metadata={"followup_id": fu.id},
        )


@ToolRegistry.register("followup_list")
class FollowupListTool(BaseTool):
    """List tracked follow-ups, optionally filtered."""

    tool_id = "followup_list"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="followup_list",
            description=(
                "List follow-ups. Filter by status, counterparty, or stale_only."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "status": {
                        "type": "string",
                        "description": "open|nudged|resolved|cancelled",
                    },
                    "counterparty": {"type": "string"},
                    "stale_only": {"type": "boolean"},
                },
            },
            category="assistant",
            requires_confirmation=False,
        )

    def execute(self, **params: Any) -> ToolResult:
        items = _followup_store().list(
            status=params.get("status") or None,
            counterparty=params.get("counterparty") or None,
            stale_only=bool(params.get("stale_only", False)),
        )
        if not items:
            return ToolResult(
                tool_name=self.spec.name, success=True, content="No follow-ups."
            )
        body = "\n".join(_format(f) for f in items)
        return ToolResult(
            tool_name=self.spec.name,
            success=True,
            content=body,
            metadata={"count": len(items)},
        )


@ToolRegistry.register("followup_resolve")
class FollowupResolveTool(BaseTool):
    """Mark a follow-up resolved or cancelled."""

    tool_id = "followup_resolve"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="followup_resolve",
            description="Close a follow-up by id (status resolved or cancelled).",
            parameters={
                "type": "object",
                "properties": {
                    "followup_id": {"type": "string"},
                    "status": {
                        "type": "string",
                        "enum": ["resolved", "cancelled"],
                    },
                },
                "required": ["followup_id"],
            },
            category="assistant",
            requires_confirmation=True,
        )

    def execute(self, **params: Any) -> ToolResult:
        fid = str(params.get("followup_id", "") or "")
        status = str(params.get("status", "resolved") or "resolved")
        try:
            fu = _followup_store().resolve(fid, status=status)
        except ValueError as exc:
            return ToolResult(
                tool_name=self.spec.name, success=False, content=str(exc)
            )
        if fu is None:
            return ToolResult(
                tool_name=self.spec.name,
                success=False,
                content=f"No follow-up {fid!r}.",
            )
        return ToolResult(
            tool_name=self.spec.name,
            success=True,
            content=f"Closed: {_format(fu)}",
        )


@ToolRegistry.register("followup_sweep_stale")
class FollowupSweepStaleTool(BaseTool):
    """Flag open follow-ups past their SLA as nudged."""

    tool_id = "followup_sweep_stale"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="followup_sweep_stale",
            description=(
                "Find open follow-ups past their sla_due_at and mark them nudged."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "now": {
                        "type": "number",
                        "description": "Optional epoch override.",
                    }
                },
            },
            category="assistant",
            requires_confirmation=True,
        )

    def execute(self, **params: Any) -> ToolResult:
        nudged = _followup_store().sweep_stale(now=params.get("now"))
        body = (
            "\n".join(_format(f) for f in nudged)
            if nudged
            else "No stale follow-ups."
        )
        return ToolResult(
            tool_name=self.spec.name,
            success=True,
            content=f"Nudged {len(nudged)} follow-up(s).\n{body}",
            metadata={"count": len(nudged)},
        )
