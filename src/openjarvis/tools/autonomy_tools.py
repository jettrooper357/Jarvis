"""Controlled Autonomy tools — rollback record/list/revert + audit report."""

from __future__ import annotations

from typing import Any

from openjarvis.autonomy.rollback_store import RollbackError, RollbackStore
from openjarvis.core.registry import ToolRegistry
from openjarvis.core.types import ToolResult
from openjarvis.tools._stubs import BaseTool, ToolSpec


def _rollback_store() -> RollbackStore:
    return RollbackStore()


def _event_log_store() -> Any:
    from openjarvis.eventlog.store import EventLogStore

    return EventLogStore()


@ToolRegistry.register("rollback_record")
class RollbackRecordTool(BaseTool):
    """Record a reversible action so it can be undone later."""

    tool_id = "rollback_record"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="rollback_record",
            description=(
                "Record a reversible action with an undo payload (e.g. "
                "file_write with prior_content) so it can be reverted later."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "action_type": {"type": "string"},
                    "summary": {"type": "string"},
                    "undo_payload": {"type": "object"},
                    "agent_id": {"type": "string"},
                    "task_id": {"type": "string"},
                    "reversible": {"type": "boolean"},
                },
                "required": ["action_type", "summary"],
            },
            category="autonomy",
        )

    def execute(self, **params: Any) -> ToolResult:
        try:
            a = _rollback_store().record(
                action_type=str(params.get("action_type", "")),
                summary=str(params.get("summary", "")),
                undo_payload=params.get("undo_payload") or {},
                agent_id=str(params.get("agent_id", "") or ""),
                task_id=str(params.get("task_id", "") or ""),
                reversible=bool(params.get("reversible", True)),
            )
        except ValueError as exc:
            return ToolResult(tool_name=self.spec.name, success=False, content=str(exc))
        return ToolResult(
            tool_name=self.spec.name,
            success=True,
            content=f"Recorded {a.action_type} ({a.status}): {a.summary}",
            metadata={"action_id": a.id, "status": a.status},
        )


@ToolRegistry.register("rollback_list")
class RollbackListTool(BaseTool):
    """List recorded reversible actions."""

    tool_id = "rollback_list"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="rollback_list",
            description=(
                "List reversible actions (filter by status/agent_id/action_type)."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "status": {"type": "string"},
                    "agent_id": {"type": "string"},
                    "action_type": {"type": "string"},
                },
            },
            category="autonomy",
        )

    def execute(self, **params: Any) -> ToolResult:
        items = _rollback_store().list(
            status=params.get("status") or None,
            agent_id=params.get("agent_id") or None,
            action_type=params.get("action_type") or None,
        )
        if not items:
            return ToolResult(
                tool_name=self.spec.name, success=True, content="No actions."
            )
        body = "\n".join(
            f"{a.id} [{a.status}] {a.action_type}: {a.summary}" for a in items
        )
        return ToolResult(
            tool_name=self.spec.name,
            success=True,
            content=body,
            metadata={"count": len(items)},
        )


@ToolRegistry.register("rollback_revert")
class RollbackRevertTool(BaseTool):
    """Revert a previously-recorded reversible action."""

    tool_id = "rollback_revert"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="rollback_revert",
            description="Revert a recorded action by id (undoes it if reversible).",
            parameters={
                "type": "object",
                "properties": {
                    "action_id": {"type": "string"},
                    "note": {"type": "string"},
                },
                "required": ["action_id"],
            },
            category="autonomy",
        )

    def execute(self, **params: Any) -> ToolResult:
        try:
            a = _rollback_store().revert(
                str(params.get("action_id", "")),
                note=str(params.get("note", "") or ""),
            )
        except RollbackError as exc:
            return ToolResult(tool_name=self.spec.name, success=False, content=str(exc))
        if a.status == "irreversible":
            return ToolResult(
                tool_name=self.spec.name,
                success=True,
                content=(
                    f"{a.action_type} is irreversible; compensating action "
                    f"required (not auto-undone)."
                ),
                metadata={"action_id": a.id, "status": a.status},
            )
        return ToolResult(
            tool_name=self.spec.name,
            success=True,
            content=f"Reverted {a.action_type}: {a.summary}",
            metadata={"action_id": a.id, "status": a.status},
        )


@ToolRegistry.register("audit_report")
class AuditReportTool(BaseTool):
    """Compile an Event Log audit report over a window."""

    tool_id = "audit_report"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="audit_report",
            description=(
                "Compile an audit report of event-log activity over a window "
                "(filter by agent_id/task_id/project_id)."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "since": {"type": "number"},
                    "until": {"type": "number"},
                    "agent_id": {"type": "string"},
                    "task_id": {"type": "string"},
                    "project_id": {"type": "string"},
                },
            },
            category="autonomy",
        )

    def execute(self, **params: Any) -> ToolResult:
        from openjarvis.autonomy.audit import build_audit_report

        report = build_audit_report(
            _event_log_store(),
            since=params.get("since"),
            until=params.get("until"),
            agent_id=params.get("agent_id") or None,
            task_id=params.get("task_id") or None,
            project_id=params.get("project_id") or None,
        )
        lines = [f"audit: {report['count']} event(s)"]
        lines += [
            f"  {e['timestamp']} {e['event_type']} (agent={e['agent_id']})"
            for e in report["events"][:50]
        ]
        return ToolResult(
            tool_name=self.spec.name,
            success=True,
            content="\n".join(lines),
            metadata={"count": report["count"]},
        )
