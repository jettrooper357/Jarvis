"""Single source of truth for cloud provider API key resolution.

Keys are saved by the UI's Cloud Models tab into
``~/.openjarvis/cloud-keys.env`` (a flat ``KEY=value`` file). Two
in-process consumers need them:

- ``openjarvis.server.cloud_router`` — the streaming
  ``/v1/chat/completions`` route, which historically read the file
  directly.
- ``openjarvis.engine.cloud.CloudEngine`` — the cloud inference engine
  used by managed agents (the Chief, monitor operatives, etc.), which
  historically read **only** ``os.environ`` and therefore missed keys
  saved through the UI when the backend was launched without them in
  the process environment.

``hydrate_env_from_cloud_keys`` is the small bridge that makes the
file-stored key visible to libraries (openai, anthropic, ...) that only
know how to read env vars. It does **not** overwrite values already
present in ``os.environ`` so a launch-time env value still wins, which
matches the precedence ``cloud_router._load_keys`` already implemented.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, Iterable, Optional

CLOUD_KEYS_FILE = Path.home() / ".openjarvis" / "cloud-keys.env"

# Provider keys + a handful of base-URL overrides that pair with them.
KNOWN_KEY_NAMES: tuple[str, ...] = (
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "GEMINI_API_KEY",
    "GOOGLE_API_KEY",
    "OPENROUTER_API_KEY",
    "MINIMAX_API_KEY",
    "OPENAI_CODEX_API_KEY",
    "OPENAI_CODEX_BASE_URL",
)


def load_cloud_keys(path: Optional[Path] = None) -> Dict[str, str]:
    """Return the merged cloud-keys map.

    File first (so live edits via the UI are picked up); ``os.environ``
    overrides each entry it touches. Lines that are blank or comments
    are ignored. Unknown keys in the file are preserved — callers can
    use them too.
    """
    p = path or CLOUD_KEYS_FILE
    keys: Dict[str, str] = {}
    if p.exists():
        try:
            for raw in p.read_text().splitlines():
                line = raw.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    keys[k.strip()] = v.strip()
        except Exception:
            # Never let a bad file break engine init; just skip the file.
            keys = {}
    for name in KNOWN_KEY_NAMES:
        val = os.environ.get(name)
        if val:
            keys[name] = val
    return keys


def hydrate_env_from_cloud_keys(
    path: Optional[Path] = None,
    names: Optional[Iterable[str]] = None,
) -> None:
    """Populate ``os.environ`` from the cloud-keys file in place.

    Only fills entries that are not already set in the environment, so a
    launch-time env value or a test-injected override is never
    clobbered. ``names`` defaults to :data:`KNOWN_KEY_NAMES`.
    """
    keys = load_cloud_keys(path)
    targets = tuple(names) if names else KNOWN_KEY_NAMES
    for name in targets:
        if not os.environ.get(name) and keys.get(name):
            os.environ[name] = keys[name]


__all__ = [
    "CLOUD_KEYS_FILE",
    "KNOWN_KEY_NAMES",
    "load_cloud_keys",
    "hydrate_env_from_cloud_keys",
]
