"""Life Manager tools — expose LifeStore (domains + routines) to agents."""

from __future__ import annotations

from typing import Any

from openjarvis.core.registry import ToolRegistry
from openjarvis.core.types import ToolResult
from openjarvis.lifemanager.store import LifeError, LifeStore
from openjarvis.tools._stubs import BaseTool, ToolSpec


def _life_store() -> LifeStore:
    return LifeStore()


@ToolRegistry.register("life_add_domain")
class LifeAddDomainTool(BaseTool):
    """Create a life domain (work/church/health/home/…)."""

    tool_id = "life_add_domain"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="life_add_domain",
            description="Create a life domain (e.g. work, church, health, home).",
            parameters={
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "slug": {"type": "string"},
                    "description": {"type": "string"},
                },
                "required": ["name"],
            },
            category="lifemanager",
        )

    def execute(self, **params: Any) -> ToolResult:
        try:
            d = _life_store().add_domain(
                name=str(params.get("name", "")),
                slug=str(params.get("slug", "") or ""),
                description=str(params.get("description", "") or ""),
            )
        except ValueError as exc:
            return ToolResult(tool_name=self.spec.name, success=False, content=str(exc))
        return ToolResult(
            tool_name=self.spec.name,
            success=True,
            content=f"Created life domain {d.name} (slug={d.slug})",
            metadata={"domain_id": d.id},
        )


@ToolRegistry.register("life_add_routine")
class LifeAddRoutineTool(BaseTool):
    """Create a recurring routine in a life domain."""

    tool_id = "life_add_routine"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="life_add_routine",
            description=(
                "Create a recurring routine. cadence is daily/weekly/monthly/"
                "custom; custom uses interval_days."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "domain_id": {"type": "string"},
                    "cadence": {
                        "type": "string",
                        "enum": ["daily", "weekly", "monthly", "custom"],
                    },
                    "interval_days": {"type": "integer"},
                },
                "required": ["title"],
            },
            category="lifemanager",
        )

    def execute(self, **params: Any) -> ToolResult:
        try:
            r = _life_store().add_routine(
                title=str(params.get("title", "")),
                domain_id=str(params.get("domain_id", "") or ""),
                cadence=str(params.get("cadence", "daily") or "daily"),
                interval_days=int(params.get("interval_days", 1) or 1),
            )
        except (ValueError, LifeError) as exc:
            return ToolResult(tool_name=self.spec.name, success=False, content=str(exc))
        return ToolResult(
            tool_name=self.spec.name,
            success=True,
            content=f"Created routine {r.title} ({r.cadence})",
            metadata={"routine_id": r.id},
        )


@ToolRegistry.register("life_complete_routine")
class LifeCompleteRoutineTool(BaseTool):
    """Mark a routine done; advances next-due and bumps the streak."""

    tool_id = "life_complete_routine"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="life_complete_routine",
            description="Mark a routine completed (advances next due, bumps streak).",
            parameters={
                "type": "object",
                "properties": {"routine_id": {"type": "string"}},
                "required": ["routine_id"],
            },
            category="lifemanager",
        )

    def execute(self, **params: Any) -> ToolResult:
        try:
            r = _life_store().complete_routine(str(params.get("routine_id", "")))
        except LifeError as exc:
            return ToolResult(tool_name=self.spec.name, success=False, content=str(exc))
        return ToolResult(
            tool_name=self.spec.name,
            success=True,
            content=f"Completed {r.title}; streak={r.streak}, next_due={r.next_due_at}",
            metadata={"routine_id": r.id, "streak": r.streak},
        )


@ToolRegistry.register("life_due")
class LifeDueTool(BaseTool):
    """List routines due now."""

    tool_id = "life_due"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="life_due",
            description="List active routines that are due now (what's owed today).",
            parameters={
                "type": "object",
                "properties": {"now": {"type": "number"}},
            },
            category="lifemanager",
        )

    def execute(self, **params: Any) -> ToolResult:
        items = _life_store().due(now=params.get("now"))
        if not items:
            return ToolResult(
                tool_name=self.spec.name, success=True, content="Nothing due."
            )
        body = "\n".join(f"{r.title} ({r.cadence})" for r in items)
        return ToolResult(
            tool_name=self.spec.name,
            success=True,
            content=body,
            metadata={"count": len(items)},
        )


@ToolRegistry.register("life_list")
class LifeListTool(BaseTool):
    """List life domains, or routines filtered by domain/status."""

    tool_id = "life_list"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="life_list",
            description=(
                "List life domains, or routines when domain_id/status is given."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "domain_id": {"type": "string"},
                    "status": {"type": "string"},
                },
            },
            category="lifemanager",
        )

    def execute(self, **params: Any) -> ToolResult:
        store = _life_store()
        domain_id = str(params.get("domain_id", "") or "")
        status = str(params.get("status", "") or "")
        if domain_id or status:
            routines = store.list_routines(
                domain_id=domain_id or None, status=status or None
            )
            body = "\n".join(f"{r.title} ({r.cadence}, {r.status})" for r in routines)
            return ToolResult(
                tool_name=self.spec.name,
                success=True,
                content=body or "No routines.",
            )
        domains = store.list_domains()
        body = "\n".join(f"{d.name} (slug={d.slug})" for d in domains)
        return ToolResult(
            tool_name=self.spec.name,
            success=True,
            content=body or "No domains.",
        )
