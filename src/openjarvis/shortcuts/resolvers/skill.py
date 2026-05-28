"""Skill resolver — runs a skill manifest end-to-end and returns the final step.

Resolves a rule whose ``target_kind = "skill"`` by:

1. Looking up the manifest via :class:`SkillManager.resolve`.
2. Executing the manifest with the supplied args as initial context.
3. Surfacing the last step's content (or a formatted multi-step summary)
   as the :class:`RawResult` content.

The manifest's optional ``metadata.default_post_prompt`` (if present)
is bubbled up so the post-processor can rewrite the output with a
skill-specific instruction.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from openjarvis.shortcuts._stubs import RawResult, Resolver

_logger = logging.getLogger("openjarvis.shortcuts.resolvers.skill")


class SkillResolver(Resolver):
    kind = "skill"

    def __init__(self, manager: Any = None) -> None:
        # Manager injection keeps unit tests cheap; production code uses
        # :func:`_default_manager` below to lazily build one bound to a
        # ToolExecutor over the global ToolRegistry.
        self._manager = manager

    def _resolve_manager(self) -> Any:
        if self._manager is not None:
            return self._manager
        try:
            from openjarvis.core.events import EventBus
            from openjarvis.core.registry import ToolRegistry
            from openjarvis.skills.manager import SkillManager
            from openjarvis.tools._stubs import ToolExecutor

            tools = []
            for name in ToolRegistry.keys():
                try:
                    tools.append(ToolRegistry.get(name)())
                except Exception:
                    continue
            bus = EventBus()
            mgr = SkillManager(bus=bus)
            mgr.set_tool_executor(ToolExecutor(tools, bus=bus))
            # Discover skills from default roots so resolution can find them.
            try:
                mgr.discover()
            except Exception:
                pass
            self._manager = mgr
        except Exception as exc:  # pragma: no cover — defensive
            _logger.warning("SkillManager bootstrap failed: %s", exc)
            self._manager = None
        return self._manager

    def resolve(self, target_id: str, args: Dict[str, Any]) -> RawResult:
        manager = self._resolve_manager()
        if manager is None:
            return RawResult(
                content="Skill subsystem unavailable",
                success=False,
                error="skill_manager_unavailable",
            )

        try:
            manifest = manager.resolve(target_id)
        except Exception as exc:
            return RawResult(
                content=f"Unknown skill: {target_id} ({exc})",
                success=False,
                error="unknown_skill",
            )

        default_post_prompt: Optional[str] = None
        try:
            metadata = getattr(manifest, "metadata", {}) or {}
            if isinstance(metadata, dict):
                default_post_prompt = metadata.get("default_post_prompt")
        except Exception:
            default_post_prompt = None

        try:
            result = manager.execute(target_id, context=dict(args))
        except Exception as exc:
            return RawResult(
                content=f"Skill execution error: {exc}",
                success=False,
                error="skill_execution_error",
                default_post_prompt=default_post_prompt,
            )

        # Collapse step outputs into a single content string. Prefer the
        # last successful step's text; fall back to joining all step
        # contents when the final step has no content.
        steps = list(getattr(result, "step_results", []) or [])
        content = ""
        if steps:
            last = steps[-1]
            content = str(getattr(last, "content", "") or "")
            if not content.strip():
                content = "\n\n".join(
                    str(getattr(s, "content", "") or "")
                    for s in steps
                    if getattr(s, "content", None)
                ).strip()
        if not content.strip():
            ctx = getattr(result, "context", {}) or {}
            content = str(ctx.get("output") or ctx.get("result") or "")

        return RawResult(
            content=content or "(skill produced no output)",
            success=bool(getattr(result, "success", False)),
            metadata={"skill": target_id, "steps": len(steps)},
            default_post_prompt=default_post_prompt,
            error=None if getattr(result, "success", False) else "skill_failed",
        )


__all__ = ["SkillResolver"]
