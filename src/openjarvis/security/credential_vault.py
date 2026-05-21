"""Run-scoped credential vault with token-based dereference.

Where :class:`CredentialScrubber` is defence in depth -- redacting any
raw secret it finds before persistence -- this vault prevents the raw
value from ever reaching the chief in the first place.

Flow on a credential resume:

1. The user supplies a secret to ``ManagedAgentRuntime.resume``.
2. The runtime stores it in the vault: ``token = vault.store(run_id, secret)``
   where ``token`` is an opaque marker like ``[[credential:abc1234567:run_xyz]]``.
3. The token (not the secret) is what the chief sees as its user
   message, so the inference engine, the chief's checkpoint, any
   delegation, and any persisted log only ever see the token.
4. Just before a tool actually executes, ``vault.resolve(arguments, run_id)``
   substitutes the token with the real value, so the tool itself
   receives what it needs.
5. ``vault.purge(run_id)`` clears the entries when the run finishes.

Tokens are opaque random strings; they carry no information about the
underlying value. Resolution requires the original ``run_id`` -- so a
stale token from one run cannot dereference a credential stored under
another.
"""

from __future__ import annotations

import re
import secrets
import threading
from typing import Dict, Iterable, Optional, Tuple

# Token marker pattern. Wide enough to be unmistakable in JSON tool
# arguments but narrow enough that legitimate text won't match.
_TOKEN_RE = re.compile(r"\[\[credential:([A-Za-z0-9]{8,32}):([^\]]+)\]\]")


def _format_token(token_id: str, run_id: str) -> str:
    return f"[[credential:{token_id}:{run_id}]]"


class CredentialVault:
    """Thread-safe, run-scoped token store for raw credentials."""

    def __init__(self) -> None:
        # (run_id, token_id) -> raw value
        self._values: Dict[Tuple[str, str], str] = {}
        self._lock = threading.Lock()

    def store(self, run_id: Optional[str], value: Optional[str]) -> Optional[str]:
        """Store ``value`` under a fresh token; return the token string.

        Returns ``None`` if ``run_id`` or ``value`` is empty -- the
        caller should treat that as "do not substitute, pass through".
        """
        if not run_id or not value:
            return None
        token_id = secrets.token_hex(8)  # 16 hex chars
        token = _format_token(token_id, str(run_id))
        with self._lock:
            self._values[(str(run_id), token_id)] = value
        return token

    def resolve(self, text: Optional[str], run_id: Optional[str]) -> str:
        """Return *text* with every vault token replaced by its raw value.

        Only tokens whose run_id matches *run_id* are substituted. A
        token from a different run is left in place (and will likely
        fail downstream, which is the desired behaviour -- a leaked
        token must not silently dereference under another run's scope).
        """
        if not text:
            return text or ""
        if not run_id:
            return text
        run_str = str(run_id)

        def _sub(match: "re.Match[str]") -> str:
            token_id = match.group(1)
            scope = match.group(2)
            if scope != run_str:
                return match.group(0)
            with self._lock:
                value = self._values.get((scope, token_id))
            return value if value is not None else match.group(0)

        return _TOKEN_RE.sub(_sub, text)

    def purge(self, run_id: Optional[str]) -> None:
        """Drop every token stored under *run_id*."""
        if not run_id:
            return
        run_str = str(run_id)
        with self._lock:
            keys_to_drop = [k for k in self._values if k[0] == run_str]
            for k in keys_to_drop:
                self._values.pop(k, None)

    def active_runs(self) -> Iterable[str]:
        """Return the set of run_ids with at least one stored secret."""
        with self._lock:
            return tuple({k[0] for k in self._values})


__all__ = ["CredentialVault"]
