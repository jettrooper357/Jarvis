"""Strict local-only reasoner guard for Watchtower."""

from __future__ import annotations

import json
from typing import Any, Dict

_CLOUD_MARKERS = (
    "openai",
    "anthropic",
    "claude",
    "gemini",
    "google",
    "openrouter",
    "api.openai.com",
    "api.anthropic.com",
    "generativelanguage.googleapis.com",
)

_LOCAL_ENGINE_KEYS = {
    "ollama",
    "llamacpp",
    "llama.cpp",
    "mlx",
    "lemonade",
    "vllm",
    "sglang",
    "local",
}


def is_local_provider(provider_config: Any) -> bool:
    """Return True only for providers that are clearly local."""
    if provider_config is None:
        return False
    if isinstance(provider_config, str):
        text = provider_config.casefold()
        if any(marker in text for marker in _CLOUD_MARKERS):
            return False
        if text in _LOCAL_ENGINE_KEYS:
            return True
        if text.startswith(("http://localhost", "http://127.0.0.1", "http://0.0.0.0")):
            return True
        return False
    if isinstance(provider_config, dict):
        text = json.dumps(provider_config, sort_keys=True).casefold()
        if any(marker in text for marker in _CLOUD_MARKERS):
            return False
        engine = str(
            provider_config.get("engine")
            or provider_config.get("provider")
            or provider_config.get("engine_key")
            or ""
        ).casefold()
        url = str(
            provider_config.get("base_url") or provider_config.get("url") or ""
        ).casefold()
        if engine in _LOCAL_ENGINE_KEYS:
            if engine in {"vllm", "sglang"} and url:
                return url.startswith(
                    ("http://localhost", "http://127.0.0.1", "http://0.0.0.0")
                )
            return True
        if url.startswith(("http://localhost", "http://127.0.0.1", "http://0.0.0.0")):
            return True
        return bool(provider_config.get("local") is True)
    engine_key = str(getattr(provider_config, "engine_key", "") or "").casefold()
    provider = str(getattr(provider_config, "provider", "") or "").casefold()
    return is_local_provider({"engine": engine_key or provider})


class LocalReasoner:
    """Optional local-only reasoner with deterministic fallback."""

    def __init__(self, provider_config: Any = None, engine: Any = None) -> None:
        self.provider_config = provider_config
        self.engine = engine
        self.last_decision = "rules_fallback"

    def available(self) -> bool:
        return bool(self.engine is not None and is_local_provider(self.provider_config))

    def reason(self, finding: Dict[str, Any]) -> Dict[str, str]:
        if not self.available():
            self.last_decision = "rules_fallback"
            return {
                "decision": "rules_fallback",
                "summary": str(
                    finding.get("reason")
                    or finding.get("finding_type")
                    or "Watchtower finding"
                ),
                "recommended_action": str(
                    finding.get("recommended_action")
                    or "Route to Chief Orchestrator for handling."
                ),
            }
        # Initial additive pass does not invoke model-specific APIs; this
        # guard is in place so later local summaries cannot accidentally use
        # paid/cloud providers.
        self.last_decision = "local_ai_available"
        return {
            "decision": "local_ai_available",
            "summary": str(
                finding.get("reason")
                or finding.get("finding_type")
                or "Watchtower finding"
            ),
            "recommended_action": str(
                finding.get("recommended_action")
                or "Route to Chief Orchestrator for handling."
            ),
        }
