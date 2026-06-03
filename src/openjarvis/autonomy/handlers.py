"""Undo-handler registry for reversible actions.

Each handler takes the action's ``undo_payload`` dict and reverses the action,
raising on failure. Inherently irreversible action types (email, deploy, …)
have NO handler — they are recorded for audit but never auto-undone.
"""

from __future__ import annotations

import os
from typing import Any, Callable, Dict, Optional

UndoHandler = Callable[[Dict[str, Any]], None]

_HANDLERS: Dict[str, UndoHandler] = {}


def register_undo_handler(action_type: str, fn: UndoHandler) -> None:
    """Register (or replace) the undo handler for ``action_type``."""
    _HANDLERS[action_type] = fn


def get_undo_handler(action_type: str) -> Optional[UndoHandler]:
    """Return the undo handler for ``action_type``, or None."""
    return _HANDLERS.get(action_type)


def has_handler(action_type: str) -> bool:
    """Whether an undo handler is registered for ``action_type``."""
    return action_type in _HANDLERS


def _undo_file_write(payload: Dict[str, Any]) -> None:
    """Restore a file's prior content, or delete it if it was newly created.

    Payload: ``{"path": str, "prior_content": str | None}``. When
    ``prior_content`` is None the file did not exist before, so it is removed.
    """
    path = str(payload.get("path") or "").strip()
    if not path:
        raise ValueError("file_write undo requires a 'path'")
    prior = payload.get("prior_content")
    if prior is None:
        if os.path.exists(path):
            os.remove(path)
        return
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(str(prior))


register_undo_handler("file_write", _undo_file_write)
