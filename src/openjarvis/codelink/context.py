"""Active work context — the task/agent/project currently being worked.

Used to stamp FileEvents and CodeChangeLinks when the caller does not pass an
explicit ``task_id``. Thread-safe and process-global.
"""

from __future__ import annotations

import threading
from contextlib import contextmanager
from typing import Dict, Iterator, Optional

_lock = threading.Lock()
_state: Dict[str, Optional[str]] = {
    "task_id": None,
    "agent_id": None,
    "project_id": None,
}


class WorkContext:
    """Process-global active work context."""

    @staticmethod
    def set(
        *,
        task_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        project_id: Optional[str] = None,
    ) -> None:
        with _lock:
            if task_id is not None:
                _state["task_id"] = task_id
            if agent_id is not None:
                _state["agent_id"] = agent_id
            if project_id is not None:
                _state["project_id"] = project_id

    @staticmethod
    def get() -> Dict[str, Optional[str]]:
        with _lock:
            return dict(_state)

    @staticmethod
    def clear() -> None:
        with _lock:
            _state["task_id"] = None
            _state["agent_id"] = None
            _state["project_id"] = None


@contextmanager
def work_context(
    *,
    task_id: Optional[str] = None,
    agent_id: Optional[str] = None,
    project_id: Optional[str] = None,
) -> Iterator[None]:
    """Set the work context for the duration of the block, then restore it."""
    prior = WorkContext.get()
    WorkContext.set(task_id=task_id, agent_id=agent_id, project_id=project_id)
    try:
        yield
    finally:
        with _lock:
            _state["task_id"] = prior["task_id"]
            _state["agent_id"] = prior["agent_id"]
            _state["project_id"] = prior["project_id"]
