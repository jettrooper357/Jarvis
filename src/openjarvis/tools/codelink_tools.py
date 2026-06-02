"""Task–Code Linkage tools — expose CodeLinkStore + WorkContext to agents."""

from __future__ import annotations

from typing import Any

from openjarvis.codelink.context import WorkContext
from openjarvis.codelink.store import CodeLinkStore
from openjarvis.core.registry import ToolRegistry
from openjarvis.core.types import ToolResult
from openjarvis.tools._stubs import BaseTool, ToolSpec


def _codelink_store() -> CodeLinkStore:
    return CodeLinkStore()


@ToolRegistry.register("codelink_set_work_context")
class CodeLinkSetWorkContextTool(BaseTool):
    """Set the active task/agent/project for subsequent change recording."""

    tool_id = "codelink_set_work_context"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="codelink_set_work_context",
            description=(
                "Set the active work context (task_id/agent_id/project_id) so "
                "later file/commit recordings are attributed to this task."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "task_id": {"type": "string"},
                    "agent_id": {"type": "string"},
                    "project_id": {"type": "string"},
                },
            },
            category="codelink",
        )

    def execute(self, **params: Any) -> ToolResult:
        WorkContext.set(
            task_id=params.get("task_id") or None,
            agent_id=params.get("agent_id") or None,
            project_id=params.get("project_id") or None,
        )
        return ToolResult(
            tool_name=self.spec.name,
            success=True,
            content=f"Work context set: {WorkContext.get()}",
        )


@ToolRegistry.register("codelink_record_file_event")
class CodeLinkRecordFileEventTool(BaseTool):
    """Record a file change explicitly."""

    tool_id = "codelink_record_file_event"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="codelink_record_file_event",
            description="Record a file change (created/modified/deleted/moved).",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "change_type": {
                        "type": "string",
                        "enum": ["created", "modified", "deleted", "moved"],
                    },
                    "task_id": {"type": "string"},
                    "old_path": {"type": "string"},
                },
                "required": ["path"],
            },
            category="codelink",
        )

    def execute(self, **params: Any) -> ToolResult:
        try:
            fe = _codelink_store().record_file_event(
                path=str(params.get("path", "")),
                change_type=str(params.get("change_type", "modified")),
                task_id=str(params.get("task_id", "") or ""),
                old_path=params.get("old_path"),
            )
        except ValueError as exc:
            return ToolResult(tool_name=self.spec.name, success=False, content=str(exc))
        return ToolResult(
            tool_name=self.spec.name,
            success=True,
            content=f"Recorded {fe.change_type} {fe.path} (task={fe.task_id})",
            metadata={"file_event_id": fe.id},
        )


@ToolRegistry.register("codelink_record_commit")
class CodeLinkRecordCommitTool(BaseTool):
    """Record the HEAD commit of a repo as a code-change link."""

    tool_id = "codelink_record_commit"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="codelink_record_commit",
            description=("Record the repo's current HEAD commit, linked to a task."),
            parameters={
                "type": "object",
                "properties": {
                    "repo_path": {"type": "string"},
                    "task_id": {"type": "string"},
                },
                "required": ["repo_path"],
            },
            category="codelink",
        )

    def execute(self, **params: Any) -> ToolResult:
        from openjarvis.codelink.git_recorder import record_head_commit

        link = record_head_commit(
            _codelink_store(),
            str(params.get("repo_path", "")),
            task_id=str(params.get("task_id", "") or ""),
        )
        if link is None:
            return ToolResult(
                tool_name=self.spec.name,
                success=False,
                content="Could not read HEAD commit for that repo.",
            )
        return ToolResult(
            tool_name=self.spec.name,
            success=True,
            content=f"Linked commit {link.commit_sha[:8]} (task={link.task_id})",
            metadata={"link_id": link.id},
        )


@ToolRegistry.register("codelink_query")
class CodeLinkQueryTool(BaseTool):
    """Query file events / commits by task or path."""

    tool_id = "codelink_query"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="codelink_query",
            description=(
                "Look up file changes and commits by task_id or path "
                "(why was this changed / which task / who)."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "task_id": {"type": "string"},
                    "path": {"type": "string"},
                },
            },
            category="codelink",
        )

    def execute(self, **params: Any) -> ToolResult:
        store = _codelink_store()
        task_id = str(params.get("task_id", "") or "")
        path = str(params.get("path", "") or "")
        if task_id:
            combined = store.events_for_task(task_id)
            fe = combined["file_events"]
            commits = combined["commits"]
            lines = [f"file_events for task {task_id}:"]
            lines += [f"  {e.change_type} {e.path}" for e in fe]
            lines.append(f"commits for task {task_id}:")
            lines += [f"  {c.commit_sha[:8]} {c.message}" for c in commits]
            return ToolResult(
                tool_name=self.spec.name,
                success=True,
                content="\n".join(lines),
            )
        if path:
            events = store.events_for_path(path)
            body = "\n".join(
                f"{e.change_type} {e.path} (task={e.task_id})" for e in events
            )
            return ToolResult(
                tool_name=self.spec.name,
                success=True,
                content=body or f"No changes recorded for {path}.",
            )
        return ToolResult(
            tool_name=self.spec.name,
            success=False,
            content="Provide task_id or path.",
        )
