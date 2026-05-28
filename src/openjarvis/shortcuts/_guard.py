"""Recursive-firing guard for shortcut resolvers.

Lives in its own module to avoid a circular import between
``openjarvis.shortcuts`` (public entry point) and the resolvers it
imports (which themselves want to suppress matching during inner runs).
"""

from __future__ import annotations

import contextlib
import contextvars
from typing import Iterator

_suppress: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "openjarvis.shortcuts.suppress",
    default=False,
)


def is_active() -> bool:
    """True when shortcut matching is currently suppressed in this context."""
    return bool(_suppress.get())


@contextlib.contextmanager
def suppress_recursive_match() -> Iterator[None]:
    """Disable shortcut matching for the duration of the ``with`` block."""
    token = _suppress.set(True)
    try:
        yield
    finally:
        _suppress.reset(token)


__all__ = ["is_active", "suppress_recursive_match"]
