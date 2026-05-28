"""REST API for the shortcut routing subsystem.

Endpoints (mounted at ``/v1/shortcuts``):

- ``GET  /``                — list rules.
- ``GET  /targets``         — enumerate available tool / skill / preset /
                              datasource target IDs the UI can pick from.
- ``GET  /{rule_id}``       — fetch one rule.
- ``POST /``                — create a rule.
- ``PUT  /{rule_id}``       — update a rule.
- ``DELETE /{rule_id}``     — delete a rule.
- ``POST /test``            — dry-run a message against the active rules.

See ``docs/superpowers/specs/2026-05-27-chat-shortcut-routing-design.md``.
"""

# NOTE: this module intentionally does NOT use ``from __future__ import
# annotations``. FastAPI / pydantic v2 needs concrete (non-stringified)
# annotations to introspect request-body models at registration time.

from dataclasses import asdict
from typing import Any, Dict, List, Optional

try:
    from pydantic import BaseModel, Field
except ImportError:  # pragma: no cover — pydantic ships with fastapi extras
    BaseModel = None  # type: ignore[assignment]
    Field = None  # type: ignore[assignment]


if BaseModel is not None:

    class PatternModel(BaseModel):
        kind: str = "phrase"
        value: str

    class RuleIn(BaseModel):
        name: str
        enabled: bool = True
        priority: int = 100
        patterns: List[PatternModel] = Field(default_factory=list)
        match_mode: str = "contains"
        case_sensitive: bool = False
        target_kind: str = "tool"
        target_id: str
        arg_template: Dict[str, Any] = Field(default_factory=dict)
        post_prompt: Optional[str] = None
        post_model: Optional[str] = None
        on_failure: str = "fallback_to_chief"
        failure_message: Optional[str] = None

    class TestIn(BaseModel):
        message: str


def _serialize_rule(rule: Any) -> Dict[str, Any]:
    return {
        "id": rule.id,
        "name": rule.name,
        "enabled": rule.enabled,
        "priority": rule.priority,
        "patterns": [asdict(p) for p in rule.patterns],
        "match_mode": rule.match_mode,
        "case_sensitive": rule.case_sensitive,
        "target_kind": rule.target_kind,
        "target_id": rule.target_id,
        "arg_template": rule.arg_template,
        "post_prompt": rule.post_prompt,
        "post_model": rule.post_model,
        "on_failure": rule.on_failure,
        "failure_message": rule.failure_message,
        "created_at": rule.created_at,
        "updated_at": rule.updated_at,
        "created_by": rule.created_by,
    }


def create_shortcuts_router(registry=None):
    """Return an APIRouter for shortcut rule CRUD.

    Importing FastAPI inside the factory mirrors the pattern used by
    other optional routers in this package. When *registry* is omitted
    (the production wiring path) the router lazily resolves the
    process-wide singleton from ``managed_agent_runtime``.
    """
    try:
        from fastapi import APIRouter, HTTPException
    except ImportError as exc:  # pragma: no cover — server extras missing
        raise ImportError(
            "fastapi and pydantic are required for the shortcuts router"
        ) from exc

    if BaseModel is None:  # pragma: no cover — defensive
        raise ImportError("pydantic is required for the shortcuts router")

    from openjarvis.shortcuts import try_shortcut
    from openjarvis.shortcuts._stubs import PatternSpec, ShortcutRule
    from openjarvis.shortcuts.registry import ShortcutRegistry

    def _registry() -> ShortcutRegistry:
        if registry is not None:
            return registry
        from openjarvis.server.managed_agent_runtime import (
            _get_shortcut_registry,
        )

        reg = _get_shortcut_registry(None)
        if reg is None:
            reg = ShortcutRegistry()
        return reg

    def _from_payload(
        payload: "RuleIn",
        *,
        rule_id: Optional[str] = None,
    ) -> ShortcutRule:
        patterns = [PatternSpec(kind=p.kind, value=p.value) for p in payload.patterns]
        return ShortcutRule(
            id=rule_id or "",
            name=payload.name,
            enabled=payload.enabled,
            priority=payload.priority,
            patterns=patterns,
            match_mode=payload.match_mode,
            case_sensitive=payload.case_sensitive,
            target_kind=payload.target_kind,
            target_id=payload.target_id,
            arg_template=payload.arg_template,
            post_prompt=payload.post_prompt,
            post_model=payload.post_model,
            on_failure=payload.on_failure,
            failure_message=payload.failure_message,
            created_by="user",
        )

    router = APIRouter(prefix="/v1/shortcuts", tags=["shortcuts"])

    @router.get("")
    async def list_rules():
        reg = _registry()
        return {
            "rules": [_serialize_rule(r) for r in reg.list(include_disabled=True)],
        }

    @router.get("/targets")
    async def list_targets():
        """Enumerate target IDs the UI can offer for each target_kind."""
        from openjarvis.core.registry import (
            ConnectorRegistry,
            SkillRegistry,
            ToolRegistry,
        )

        def _keys(reg) -> list:
            try:
                return sorted(reg.keys())
            except Exception:
                return []

        return {
            "tool": _keys(ToolRegistry),
            "skill": _keys(SkillRegistry),
            "datasource": _keys(ConnectorRegistry),
            "preset": [],
        }

    @router.get("/{rule_id}")
    async def get_rule(rule_id: str):
        reg = _registry()
        rule = reg.get(rule_id)
        if rule is None:
            raise HTTPException(status_code=404, detail="rule_not_found")
        return _serialize_rule(rule)

    @router.post("")
    async def create_rule(payload: RuleIn):
        reg = _registry()
        rule = _from_payload(payload)
        saved = reg.upsert(rule)
        return _serialize_rule(saved)

    @router.put("/{rule_id}")
    async def update_rule(rule_id: str, payload: RuleIn):
        reg = _registry()
        existing = reg.get(rule_id)
        if existing is None:
            raise HTTPException(status_code=404, detail="rule_not_found")
        rule = _from_payload(payload, rule_id=rule_id)
        rule.created_at = existing.created_at
        rule.created_by = existing.created_by
        saved = reg.upsert(rule)
        return _serialize_rule(saved)

    @router.delete("/{rule_id}")
    async def delete_rule(rule_id: str):
        reg = _registry()
        if not reg.delete(rule_id):
            raise HTTPException(status_code=404, detail="rule_not_found")
        return {"deleted": rule_id}

    @router.post("/test")
    async def test_match(payload: TestIn):
        """Dry-run a message — runs the resolver but skips post-processing."""
        reg = _registry()
        outcome = try_shortcut(
            payload.message,
            registry=reg,
            post_engine=None,
            post_model=None,
        )
        return {
            "matched": outcome.matched,
            "handled": outcome.handled,
            "success": outcome.success,
            "rule_id": outcome.rule_id,
            "rule_name": outcome.rule_name,
            "target_kind": outcome.target_kind,
            "target_id": outcome.target_id,
            "content": outcome.content,
            "fallback_to_chief": outcome.fallback_to_chief,
            "error": outcome.error,
            "used_post_prompt": outcome.used_post_prompt,
        }

    return router


__all__ = ["create_shortcuts_router"]
