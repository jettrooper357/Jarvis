"""Preset resolver — runs a one-shot turn using a saved agent template.

A "preset" in OpenJarvis is an agent template TOML under
``~/.openjarvis/templates/`` or the built-in templates directory. This
resolver loads the template, extracts its ``system_prompt_template``
(substituting ``{instruction}`` with the user message), and runs a
single :meth:`InferenceEngine.generate` call. The result becomes the
:class:`RawResult` content.

A one-shot generate avoids re-entering the Chief tool-calling loop —
which would otherwise need the recursive-firing guard to be load-bearing
under every code path. The guard is still active via
:func:`openjarvis.shortcuts.suppress_recursive_match` so any future tool-
using extension stays safe.

Engine and default model are injected at construction time. Callers that
omit them get a resolver that returns a sensible "engine not configured"
:class:`RawResult` so missing wiring is observable rather than silent.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from openjarvis.shortcuts._guard import suppress_recursive_match
from openjarvis.shortcuts._stubs import RawResult, Resolver

_logger = logging.getLogger("openjarvis.shortcuts.resolvers.preset")


def _format_prompt(template_body: str, args: Dict[str, Any]) -> str:
    """Substitute ``{instruction}`` and any other ``{slot}`` keys."""
    instruction = str(args.get("instruction") or args.get("query") or "").strip()
    safe = {**args, "instruction": instruction}
    try:
        return template_body.format_map(_SafeDict(safe))
    except Exception:
        return template_body


class _SafeDict(dict):
    """``str.format_map`` helper — unknown keys render as empty strings."""

    def __missing__(self, key: str) -> str:
        return ""


class PresetResolver(Resolver):
    kind = "preset"

    def __init__(
        self,
        engine: Any = None,
        model: Optional[str] = None,
        *,
        temperature: float = 0.3,
        max_tokens: int = 1024,
    ) -> None:
        self._engine = engine
        self._model = model
        self._temperature = temperature
        self._max_tokens = max_tokens

    def _load_template(self, target_id: str) -> Optional[Dict[str, Any]]:
        try:
            from openjarvis.agents.library import (
                get_template_document,
                parse_template_content,
            )

            doc = get_template_document(target_id)
            parsed = parse_template_content(doc.get("content", ""))
            return parsed
        except FileNotFoundError:
            return None
        except Exception as exc:
            _logger.warning("Failed to load template %s: %s", target_id, exc)
            return None

    def resolve(self, target_id: str, args: Dict[str, Any]) -> RawResult:
        template = self._load_template(target_id)
        if template is None:
            return RawResult(
                content=f"Unknown preset: {target_id}",
                success=False,
                error="unknown_preset",
            )

        system_prompt = str(
            template.get("system_prompt_template")
            or template.get("system_prompt")
            or ""
        )
        user_message = str(
            args.get("message") or args.get("instruction") or args.get("query") or ""
        )
        formatted_system = _format_prompt(system_prompt, args)
        default_post_prompt = None
        meta = template.get("metadata")
        if isinstance(meta, dict):
            default_post_prompt = meta.get("default_post_prompt")

        if self._engine is None:
            return RawResult(
                content="Preset resolver has no inference engine configured.",
                success=False,
                error="no_engine",
                default_post_prompt=default_post_prompt,
            )

        model = (
            (args.get("model") if isinstance(args.get("model"), str) else None)
            or template.get("model")
            or self._model
        )
        if not model:
            return RawResult(
                content="Preset resolver has no model configured.",
                success=False,
                error="no_model",
                default_post_prompt=default_post_prompt,
            )

        try:
            from openjarvis.core.types import Message, Role
        except Exception as exc:  # pragma: no cover — core types always present
            return RawResult(
                content=f"Preset resolver bootstrap failed: {exc}",
                success=False,
                error="bootstrap_failed",
                default_post_prompt=default_post_prompt,
            )

        messages: list = []
        if formatted_system:
            messages.append(Message(role=Role.SYSTEM, content=formatted_system))
        messages.append(Message(role=Role.USER, content=user_message))

        try:
            with suppress_recursive_match():
                response = self._engine.generate(
                    messages,
                    model=str(model),
                    temperature=float(template.get("temperature") or self._temperature),
                    max_tokens=int(template.get("max_tokens") or self._max_tokens),
                )
        except Exception as exc:
            return RawResult(
                content=f"Preset run failed: {exc}",
                success=False,
                error="preset_run_failed",
                default_post_prompt=default_post_prompt,
            )

        text = (response or {}).get("content") or ""
        if not text.strip():
            return RawResult(
                content="(preset produced no output)",
                success=False,
                error="empty_response",
                default_post_prompt=default_post_prompt,
                metadata={"preset": target_id, "model": str(model)},
            )

        return RawResult(
            content=str(text),
            success=True,
            metadata={"preset": target_id, "model": str(model)},
            default_post_prompt=default_post_prompt,
        )


__all__ = ["PresetResolver"]
