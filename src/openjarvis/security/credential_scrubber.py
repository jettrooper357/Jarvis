"""Run-scoped credential scrubber.

Tracks plaintext secrets that flow into the chief during a single run
(typically arriving via an ``auth_required`` pause + resume) and removes
them from anything we are about to persist. The scrubber is *not* a
substitute for treating credentials carefully -- it is a defence in
depth at the persistence boundary so a credential that the chief might
otherwise have embedded into a delegation message or tool argument does
not end up sitting in ``agent_messages`` or any downstream log.

Scope rules:

- Secrets are registered against a ``run_id`` and only scrubbed from
  text that carries the same ``run_id``. A scrub call for a different
  run is a no-op, so unrelated work isn't accidentally rewritten.
- Secrets shorter than ``MIN_SECRET_LENGTH`` are not tracked. Tokens
  like "1234" would over-scrub legitimate text.
- ``purge(run_id)`` clears the secrets for that run; callers are
  responsible for invoking it in a ``finally`` block once the run is
  finished so nothing lingers in memory beyond its lifetime.
"""

from __future__ import annotations

import threading
from typing import Dict, Iterable, Optional, Set

MIN_SECRET_LENGTH = 8
REDACTION_PLACEHOLDER = "[credential redacted]"


class CredentialScrubber:
    """Thread-safe, run-scoped secret tracker for the managed-agent runtime."""

    def __init__(self) -> None:
        self._secrets: Dict[str, Set[str]] = {}
        self._lock = threading.Lock()

    def register(self, run_id: Optional[str], value: Optional[str]) -> bool:
        """Track ``value`` as a secret for ``run_id``.

        Returns True if the value was registered, False if it was
        rejected (empty, too short, or no run_id). Short values are
        rejected because substring scrubbing on them risks rewriting
        unrelated text -- e.g., a 4-digit token might appear inside
        normal prose.
        """
        if not run_id:
            return False
        if not value or len(value) < MIN_SECRET_LENGTH:
            return False
        with self._lock:
            self._secrets.setdefault(str(run_id), set()).add(value)
        return True

    def scrub(self, text: Optional[str], run_id: Optional[str]) -> str:
        """Return *text* with every secret tracked for ``run_id`` redacted.

        Returns ``""`` when *text* is falsy. Unknown ``run_id`` -> the
        text is returned unchanged.
        """
        if not text:
            return text or ""
        if not run_id:
            return text
        with self._lock:
            secrets = tuple(self._secrets.get(str(run_id), ()))
        out = text
        for secret in secrets:
            if secret and secret in out:
                out = out.replace(secret, REDACTION_PLACEHOLDER)
        return out

    def purge(self, run_id: Optional[str]) -> None:
        """Drop every secret tracked for ``run_id``."""
        if not run_id:
            return
        with self._lock:
            self._secrets.pop(str(run_id), None)

    def active_runs(self) -> Iterable[str]:
        """Return the set of run_ids with at least one tracked secret."""
        with self._lock:
            return tuple(self._secrets.keys())


__all__ = [
    "CredentialScrubber",
    "MIN_SECRET_LENGTH",
    "REDACTION_PLACEHOLDER",
]
