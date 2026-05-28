"""Optional LLM rewrite for a shortcut's raw result.

Precedence for the effective post-prompt: rule override → target default →
none. ``None`` or empty-string means pass the raw content through
unchanged.

Precedence for the model: rule override → configured global default →
caller-supplied fallback (typically the Chief's active engine + model).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from openjarvis.core.types import Message, Role
from openjarvis.engine._stubs import InferenceEngine
from openjarvis.shortcuts._stubs import RawResult

_logger = logging.getLogger("openjarvis.shortcuts.post_processor")


@dataclass(slots=True)
class PostProcessOutcome:
    content: str
    used_prompt: Optional[str]
    used_model: Optional[str]
    success: bool
    error: Optional[str] = None


def _resolve_prompt(
    rule_prompt: Optional[str], default_prompt: Optional[str]
) -> Optional[str]:
    if rule_prompt is None:
        return default_prompt
    return rule_prompt  # empty string ⇒ explicit passthrough


def run(
    raw: RawResult,
    *,
    rule_prompt: Optional[str],
    default_prompt_from_target: Optional[str],
    engine: Optional[InferenceEngine],
    model: Optional[str],
    temperature: float = 0.3,
    max_tokens: int = 800,
) -> PostProcessOutcome:
    """Apply the configured post-processor.

    Returns the rewritten text on success, or the raw content on
    failure / passthrough.
    """
    effective_prompt = _resolve_prompt(rule_prompt, default_prompt_from_target)

    if not effective_prompt:
        return PostProcessOutcome(
            content=raw.content,
            used_prompt=None,
            used_model=None,
            success=True,
        )

    if engine is None or not model:
        # No engine/model wired — fall back to raw content but keep the
        # subsystem honest about what happened.
        return PostProcessOutcome(
            content=raw.content,
            used_prompt=effective_prompt,
            used_model=None,
            success=False,
            error="no_engine_or_model",
        )

    messages = [
        Message(role=Role.SYSTEM, content=effective_prompt),
        Message(role=Role.USER, content=raw.content),
    ]
    try:
        result = engine.generate(
            messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        text = (result or {}).get("content") or ""
        if not text.strip():
            return PostProcessOutcome(
                content=raw.content,
                used_prompt=effective_prompt,
                used_model=model,
                success=False,
                error="empty_response",
            )
        return PostProcessOutcome(
            content=text,
            used_prompt=effective_prompt,
            used_model=model,
            success=True,
        )
    except Exception as exc:
        _logger.warning("Shortcut post-processor failed: %s", exc)
        return PostProcessOutcome(
            content=raw.content,
            used_prompt=effective_prompt,
            used_model=model,
            success=False,
            error=str(exc),
        )


__all__ = ["PostProcessOutcome", "run"]
