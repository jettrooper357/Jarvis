"""Shortcut routing subsystem — deterministic phrase → target → post-processor.

See ``docs/superpowers/specs/2026-05-27-chat-shortcut-routing-design.md``
and ``docs/CHANGE_IMPACT_NOTICES/chat-shortcut-routing.md``.

The public entry point is :func:`try_shortcut`, which the Chief
Orchestrator calls before its first LLM round-trip on each turn.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, Optional

from openjarvis.core.events import EventBus
from openjarvis.engine._stubs import InferenceEngine
from openjarvis.shortcuts import matcher, post_processor
from openjarvis.shortcuts._guard import is_active as _suppress_active
from openjarvis.shortcuts._guard import suppress_recursive_match  # noqa: F401
from openjarvis.shortcuts._stubs import (
    MatchResult,
    PatternSpec,
    RawResult,
    Resolver,
    ShortcutRule,
)
from openjarvis.shortcuts.registry import ShortcutRegistry
from openjarvis.shortcuts.resolvers import default_resolvers

_logger = logging.getLogger("openjarvis.shortcuts")


@dataclass(slots=True)
class ShortcutOutcome:
    """Result of attempting a shortcut for one user message."""

    matched: bool
    handled: bool
    content: str = ""
    success: bool = False
    rule_id: Optional[str] = None
    rule_name: Optional[str] = None
    target_kind: Optional[str] = None
    target_id: Optional[str] = None
    used_post_prompt: Optional[str] = None
    used_post_model: Optional[str] = None
    error: Optional[str] = None
    fallback_to_chief: bool = False
    raw_metadata: Dict[str, Any] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.raw_metadata is None:
            self.raw_metadata = {}


def _publish(bus: Optional[EventBus], name: str, payload: Dict[str, Any]) -> None:
    if bus is None:
        return
    try:
        bus.publish(name, payload)
    except Exception:
        pass


def try_shortcut(
    user_message: str,
    *,
    registry: ShortcutRegistry,
    resolvers: Optional[Dict[str, Resolver]] = None,
    post_engine: Optional[InferenceEngine] = None,
    post_model: Optional[str] = None,
    bus: Optional[EventBus] = None,
) -> ShortcutOutcome:
    """Try to handle *user_message* via a registered shortcut.

    Returns a :class:`ShortcutOutcome` describing what happened. The
    Chief uses this to decide whether to skip its decision LLM call:

    - ``matched=False`` → no rule fired; run a normal Chief turn.
    - ``matched=True, handled=True`` → use ``content`` as the final
      reply (still wrapped through Chief's final-report path).
    - ``matched=True, handled=False, fallback_to_chief=True`` → resolver
      failed and the rule's policy is to fall back; run a normal turn.
    - ``matched=True, handled=True, success=False`` → ``on_failure`` is
      ``error`` or ``custom_message`` and the outcome is terminal.
    """
    resolver_map = (
        resolvers
        if resolvers is not None
        else default_resolvers(engine=post_engine, model=post_model)
    )
    rules = registry.list(include_disabled=False)

    # Recursive-firing guard: when an inner-resolver path (notably the
    # preset resolver's one-shot agent run) is already inside a shortcut
    # turn, suppress further shortcut matching to avoid loops.
    if _suppress_active():
        return ShortcutOutcome(matched=False, handled=False)

    result: Optional[MatchResult] = matcher.match(user_message, rules)

    unsafe = matcher.drain_unsafe_rule_ids()
    for unsafe_id in unsafe:
        try:
            rule_record = registry.get(unsafe_id)
            if rule_record is not None and rule_record.enabled:
                rule_record.enabled = False
                registry.upsert(rule_record)
            _publish(
                bus,
                "shortcut.rule.disabled_unsafe",
                {"rule_id": unsafe_id, "reason": "match_timeout"},
            )
        except Exception:
            _logger.warning("Failed to disable unsafe rule %s", unsafe_id)

    if result is None:
        return ShortcutOutcome(matched=False, handled=False)

    rule = result.rule
    _publish(
        bus,
        "shortcut.matched",
        {
            "rule_id": rule.id,
            "rule_name": rule.name,
            "target_kind": rule.target_kind,
            "target_id": rule.target_id,
            "args": result.resolved_args,
            "matched_text": result.matched_text,
        },
    )

    resolver = resolver_map.get(rule.target_kind)
    if resolver is None:
        _logger.info(
            "No resolver registered for target_kind=%s (rule %s)",
            rule.target_kind,
            rule.id,
        )
        return _apply_failure(
            rule,
            error=f"no_resolver_for_{rule.target_kind}",
            bus=bus,
            result=result,
        )

    raw = resolver.resolve(rule.target_id, dict(result.resolved_args))
    _publish(
        bus,
        "shortcut.resolved",
        {
            "rule_id": rule.id,
            "success": raw.success,
            "target_kind": rule.target_kind,
            "target_id": rule.target_id,
        },
    )

    if not raw.success:
        return _apply_failure(
            rule,
            error=raw.error or "resolver_failed",
            bus=bus,
            result=result,
            raw=raw,
        )

    pp = post_processor.run(
        raw,
        rule_prompt=rule.post_prompt,
        default_prompt_from_target=raw.default_post_prompt,
        engine=post_engine,
        model=rule.post_model or post_model,
    )
    if pp.used_prompt is not None:
        _publish(
            bus,
            "shortcut.post_processor.finished"
            if pp.success
            else "shortcut.post_processor.failed",
            {
                "rule_id": rule.id,
                "success": pp.success,
                "used_model": pp.used_model,
                "error": pp.error,
            },
        )

    return ShortcutOutcome(
        matched=True,
        handled=True,
        success=True,
        content=pp.content,
        rule_id=rule.id,
        rule_name=rule.name,
        target_kind=rule.target_kind,
        target_id=rule.target_id,
        used_post_prompt=pp.used_prompt,
        used_post_model=pp.used_model,
        raw_metadata=raw.metadata,
    )


def _apply_failure(
    rule: ShortcutRule,
    *,
    error: str,
    bus: Optional[EventBus],
    result: MatchResult,
    raw: Optional[RawResult] = None,
) -> ShortcutOutcome:
    policy = rule.on_failure or "fallback_to_chief"
    if policy == "error":
        _publish(
            bus,
            "shortcut.failed",
            {"rule_id": rule.id, "error": error, "policy": policy},
        )
        return ShortcutOutcome(
            matched=True,
            handled=True,
            success=False,
            content=f"Shortcut '{rule.name}' failed: {error}",
            rule_id=rule.id,
            rule_name=rule.name,
            target_kind=rule.target_kind,
            target_id=rule.target_id,
            error=error,
        )
    if policy == "custom_message":
        _publish(
            bus,
            "shortcut.failed",
            {"rule_id": rule.id, "error": error, "policy": policy},
        )
        return ShortcutOutcome(
            matched=True,
            handled=True,
            success=True,
            content=rule.failure_message or "Shortcut unavailable right now.",
            rule_id=rule.id,
            rule_name=rule.name,
            target_kind=rule.target_kind,
            target_id=rule.target_id,
            error=error,
        )
    _publish(
        bus,
        "shortcut.fallback",
        {"rule_id": rule.id, "error": error, "policy": policy},
    )
    return ShortcutOutcome(
        matched=True,
        handled=False,
        success=False,
        rule_id=rule.id,
        rule_name=rule.name,
        target_kind=rule.target_kind,
        target_id=rule.target_id,
        error=error,
        fallback_to_chief=True,
    )


__all__ = [
    "MatchResult",
    "PatternSpec",
    "RawResult",
    "Resolver",
    "ShortcutOutcome",
    "ShortcutRegistry",
    "ShortcutRule",
    "suppress_recursive_match",
    "try_shortcut",
]
