"""Active project workspace sandbox.

When a managed agent runs on behalf of a project task, this module
exposes the project's ``working_folder`` as the active sandbox root for
filesystem and shell tools. Tools that touch disk consult
``active_workspace_root()`` and reject paths that escape the root.

The root is tracked in a ``contextvars.ContextVar`` so concurrent agent
runs in the same process don't bleed into each other.
"""

from __future__ import annotations

import contextlib
from contextvars import ContextVar
from pathlib import Path
from typing import Iterator, Optional

_active_workspace: ContextVar[str] = ContextVar(
    "openjarvis_active_workspace", default=""
)


def active_workspace_root() -> str:
    """Return the active project working folder, or '' if none."""
    return _active_workspace.get() or ""


def set_active_workspace(path: str) -> object:
    """Set the active workspace root for the current context.

    Returns the token that ``contextvars.ContextVar.reset`` requires.
    Prefer the ``use_workspace`` context manager unless you need manual
    lifetime control.
    """
    return _active_workspace.set(str(path or ""))


def reset_active_workspace(token: object) -> None:
    """Reset the active workspace back to its prior value."""
    try:
        _active_workspace.reset(token)  # type: ignore[arg-type]
    except (ValueError, LookupError):
        _active_workspace.set("")


@contextlib.contextmanager
def use_workspace(path: str) -> Iterator[str]:
    """Context manager that activates ``path`` as the workspace root."""
    token = _active_workspace.set(str(path or ""))
    try:
        yield active_workspace_root()
    finally:
        try:
            _active_workspace.reset(token)
        except (ValueError, LookupError):
            _active_workspace.set("")


def _resolve(path: Path) -> Path:
    """Resolve a path without requiring it to exist."""
    try:
        return path.resolve()
    except OSError:
        return path.absolute()


def is_within_workspace(path: str | Path) -> bool:
    """True when ``path`` is inside the active workspace (or none is set)."""
    root_str = active_workspace_root()
    if not root_str:
        return True
    root = _resolve(Path(root_str))
    target = _resolve(Path(path).expanduser())
    try:
        return target == root or target.is_relative_to(root)
    except AttributeError:
        # Pythons < 3.9 (we target 3.10+ so this is paranoia)
        try:
            target.relative_to(root)
            return True
        except ValueError:
            return False


def resolve_within_workspace(path: str | Path) -> Optional[Path]:
    """Return the resolved path if it lives under the workspace, else None.

    A relative path is interpreted relative to the workspace root when
    one is active; otherwise it is resolved against the current working
    directory.
    """
    root_str = active_workspace_root()
    p = Path(path).expanduser()
    if root_str and not p.is_absolute():
        p = Path(root_str) / p
    resolved = _resolve(p)
    if not is_within_workspace(resolved):
        return None
    return resolved


__all__ = [
    "active_workspace_root",
    "set_active_workspace",
    "reset_active_workspace",
    "use_workspace",
    "is_within_workspace",
    "resolve_within_workspace",
]
