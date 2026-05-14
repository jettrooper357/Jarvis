"""Auto-discover available text-to-speech backends.

Mirrors ``_discovery.py`` for STT. Returns the first healthy backend in
priority order, defaulting to the local ``kokoro`` engine.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from openjarvis.core.config import JarvisConfig
    from openjarvis.speech.tts import TTSBackend


DISCOVERY_ORDER = ["kokoro", "cartesia", "openai"]


def _create_backend(
    key: str,
    config: "JarvisConfig",
) -> Optional["TTSBackend"]:
    from openjarvis.core.registry import TTSRegistry

    if not TTSRegistry.contains(key):
        return None

    try:
        backend_cls = TTSRegistry.get(key)
        if key == "kokoro":
            return backend_cls()
        if key == "cartesia":
            api_key = os.environ.get("CARTESIA_API_KEY", "")
            if not api_key:
                return None
            return backend_cls(api_key=api_key)
        if key == "openai":
            api_key = os.environ.get("OPENAI_API_KEY", "")
            if not api_key:
                return None
            return backend_cls(api_key=api_key)
        return backend_cls()
    except Exception:
        return None


def get_tts_backend(config: "JarvisConfig") -> Optional["TTSBackend"]:
    """Resolve a TTS backend, defaulting to local kokoro."""
    import openjarvis.speech  # noqa: F401 — trigger registration

    backend_key = getattr(getattr(config, "tts", None), "backend", "auto")

    if backend_key and backend_key != "auto":
        return _create_backend(backend_key, config)

    for key in DISCOVERY_ORDER:
        backend = _create_backend(key, config)
        if backend is not None:
            return backend

    return None


__all__ = ["get_tts_backend"]
