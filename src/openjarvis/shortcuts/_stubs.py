"""Dataclasses and ABCs for the shortcut routing subsystem.

A shortcut is a deterministic phrase/regex rule that maps an incoming user
message to a tool / skill / preset / data-source query, optionally rewriting
the raw result through a post-processor LLM call.

See ``docs/superpowers/specs/2026-05-27-chat-shortcut-routing-design.md``.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, ClassVar, Dict, List, Optional


@dataclass(slots=True)
class PatternSpec:
    """One pattern row inside a rule's ``patterns`` list.

    ``kind`` is ``"phrase"`` or ``"regex"``. Phrase values may include
    ``{slot}`` placeholders which the matcher converts to non-greedy
    named groups internally.
    """

    kind: str
    value: str


@dataclass(slots=True)
class ShortcutRule:
    """A user-authored or system-seeded routing rule."""

    id: str
    name: str
    enabled: bool = True
    priority: int = 100
    patterns: List[PatternSpec] = field(default_factory=list)
    match_mode: str = "contains"
    case_sensitive: bool = False
    target_kind: str = "tool"
    target_id: str = ""
    arg_template: Dict[str, Any] = field(default_factory=dict)
    post_prompt: Optional[str] = None
    post_model: Optional[str] = None
    on_failure: str = "fallback_to_chief"
    failure_message: Optional[str] = None
    created_at: str = ""
    updated_at: str = ""
    created_by: str = "user"


@dataclass(slots=True)
class MatchResult:
    """Outcome of a successful match against an inbound user message."""

    rule: ShortcutRule
    matched_text: str
    slots: Dict[str, str] = field(default_factory=dict)
    resolved_args: Dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class RawResult:
    """Normalized output from any resolver."""

    content: str
    success: bool
    metadata: Dict[str, Any] = field(default_factory=dict)
    artifacts: List[str] = field(default_factory=list)
    default_post_prompt: Optional[str] = None
    error: Optional[str] = None


class Resolver(ABC):
    """Resolves one ``target_kind`` to a :class:`RawResult`."""

    kind: ClassVar[str] = ""

    @abstractmethod
    def resolve(self, target_id: str, args: Dict[str, Any]) -> RawResult:
        """Execute the target and return a normalized result."""


__all__ = [
    "MatchResult",
    "PatternSpec",
    "RawResult",
    "Resolver",
    "ShortcutRule",
]
