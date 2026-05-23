"""Phase 2F — bounded worker pool for background delegation execution.

When ``background_delegation.enabled`` is set, an immediate-kickoff
delegation (``managed_agent_assign_task(start_now=True)``) enqueues the
subordinate's kickoff turn here instead of running it inline on the
delegating agent's thread. Each job calls the unchanged
``ManagedAgentRuntime.run(...)``; the pool only changes *where* that
runs. See ``docs/CHANGE_IMPACT_NOTICES/background-delegation-execution.md``.
"""

from __future__ import annotations

import atexit
import logging
import threading
from concurrent.futures import Future, ThreadPoolExecutor, wait
from typing import Any, Callable, Optional, Sequence

logger = logging.getLogger(__name__)

OnComplete = Callable[[Optional[str], Optional[BaseException]], None]


class BackgroundDelegationExecutor:
    """Bounded thread pool that runs subordinate kickoff turns.

    A job is one ``runtime.run(...)`` call. The pool is bounded by
    ``max_workers``; excess jobs queue. A job never raises into the
    worker — any exception is captured and handed to ``on_complete``.
    """

    def __init__(self, max_workers: int = 2) -> None:
        self._max_workers = max(1, int(max_workers))
        self._pool = ThreadPoolExecutor(
            max_workers=self._max_workers,
            thread_name_prefix="bg-delegation",
        )
        self._lock = threading.Lock()
        self._futures: set[Future[None]] = set()

    @property
    def inflight(self) -> int:
        """Jobs submitted and not yet finished (queued + running)."""
        with self._lock:
            return len(self._futures)

    def submit(
        self,
        *,
        runtime: Any,
        agent_id: str,
        kickoff_message: str,
        parent_agent_id: str = "",
        visited_agent_ids: Sequence[str] = (),
        on_complete: Optional[OnComplete] = None,
        task_session_id: Optional[str] = None,
    ) -> None:
        """Enqueue a subordinate kickoff turn for background execution.

        ``task_session_id`` (Phase 2G) scopes the subordinate's writes and
        history reads to a per-task session inside the worker's message
        log. ``None`` / empty means the subordinate runs against its
        general session (today's behaviour).
        """
        visited = tuple(visited_agent_ids)
        future: Future[None] = self._pool.submit(
            self._run_job,
            runtime,
            agent_id,
            kickoff_message,
            parent_agent_id,
            visited,
            on_complete,
            task_session_id,
        )
        with self._lock:
            self._futures.add(future)
        future.add_done_callback(self._discard_future)

    def _discard_future(self, future: Future[None]) -> None:
        with self._lock:
            self._futures.discard(future)

    def _run_job(
        self,
        runtime: Any,
        agent_id: str,
        kickoff_message: str,
        parent_agent_id: str,
        visited: tuple[str, ...],
        on_complete: Optional[OnComplete],
        task_session_id: Optional[str] = None,
    ) -> None:
        result: Optional[str] = None
        error: Optional[BaseException] = None
        try:
            result = runtime.run(
                agent_id,
                kickoff_message,
                parent_agent_id=parent_agent_id,
                visited_agent_ids=visited,
                task_session_id=task_session_id,
            )
        except Exception as exc:  # a job must never kill the worker
            error = exc
            logger.exception(
                "Background delegation job failed for agent %s", agent_id
            )
        if on_complete is not None:
            try:
                on_complete(result, error)
            except Exception:
                logger.exception(
                    "Background delegation on_complete callback failed for %s",
                    agent_id,
                )

    def shutdown(self, *, timeout: float = 5.0) -> None:
        """Drain briefly, then log and abandon anything still running."""
        with self._lock:
            pending = list(self._futures)
        if pending:
            _, not_done = wait(pending, timeout=timeout)
            if not_done:
                logger.warning(
                    "Background delegation: %d job(s) abandoned at shutdown",
                    len(not_done),
                )
        self._pool.shutdown(wait=False, cancel_futures=True)


def make_parent_notification_callback(
    manager: Any,
    *,
    parent_agent_id: str,
    target_name: str,
    task_id: str,
    worker_agent_id: str = "",
    worker_session_id: str = "",
    bus: Any = None,
    summary_limit: int = 600,
) -> OnComplete:
    """Build an ``on_complete`` callback that reports back up the chain.

    Phase 2F Option B — when a background subordinate turn finishes, post
    a short completion (or failure) message to the **parent** agent's
    message log so the upward return path is honored. The parent picks
    it up on its next turn; this callback does not re-dispatch the
    parent, only informs it.

    Phase 2G — when ``worker_session_id`` is non-empty, the callback also
    emits ``AGENT_SESSION_MERGED`` on the supplied ``bus`` after the
    parent notification succeeds, marking the per-task session closed.
    """

    def _on_complete(
        result: Optional[str], error: Optional[BaseException]
    ) -> None:
        if not parent_agent_id:
            return  # nothing to roll back up to
        if error is not None:
            content = (
                f"Background task {task_id} delegated to {target_name} "
                f"failed: {error}"
            )
        else:
            summary = str(result or "").strip()
            if len(summary) > summary_limit:
                summary = summary[: summary_limit - 3] + "..."
            content = (
                f"Background task {task_id} delegated to {target_name} "
                f"finished: {summary}"
            )
        try:
            manager.send_message(parent_agent_id, content, mode="delegated")
        except Exception:
            logger.exception(
                "Background delegation: failed to notify parent %s for task %s",
                parent_agent_id,
                task_id,
            )
            return
        if worker_session_id and bus is not None:
            try:
                from openjarvis.core.events import EventType

                bus.publish(
                    EventType.AGENT_SESSION_MERGED,
                    {
                        "parent_agent_id": parent_agent_id,
                        "worker_agent_id": worker_agent_id,
                        "task_id": task_id,
                        "session_id": worker_session_id,
                    },
                )
            except Exception:
                logger.exception(
                    "Background delegation: failed to emit session merged event"
                )

    return _on_complete


_executor: Optional[BackgroundDelegationExecutor] = None
_executor_lock = threading.Lock()


def get_background_delegation_executor(
    max_workers: int = 2,
) -> BackgroundDelegationExecutor:
    """Return the process-wide executor, creating it on first use.

    ``max_workers`` is honored only on the creating call; later calls
    return the existing executor unchanged.
    """
    global _executor
    with _executor_lock:
        if _executor is None:
            _executor = BackgroundDelegationExecutor(max_workers=max_workers)
            atexit.register(_shutdown_at_exit)
        return _executor


def _shutdown_at_exit() -> None:
    if _executor is not None:
        try:
            _executor.shutdown()
        except Exception:
            logger.exception("Background delegation executor shutdown failed")


def reset_background_delegation_executor() -> None:
    """Test hook — drain and drop the process-wide executor.

    Waits briefly for in-flight jobs to finish so a stale background
    thread from a prior test can't reach into a manager its test has
    already closed. Test-only; production code uses the atexit hook.
    """
    global _executor
    with _executor_lock:
        previous = _executor
        _executor = None
    if previous is not None:
        previous.shutdown(timeout=5.0)
