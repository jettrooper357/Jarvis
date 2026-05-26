"""AgentScheduler — cron/interval tick scheduling for managed agents."""

from __future__ import annotations

import logging
import threading
import time
from typing import TYPE_CHECKING, Any

from openjarvis.core.events import EventType

if TYPE_CHECKING:
    from openjarvis.agents.executor import AgentExecutor
    from openjarvis.agents.manager import AgentManager

logger = logging.getLogger(__name__)


def _next_cron_fire(cron_expr: str, now: float | None = None) -> float:
    """Calculate the next fire time for a cron expression.

    Uses croniter if available, otherwise falls back to a simple
    interval-based approximation.
    """
    try:
        from croniter import croniter
    except ImportError:
        # Fallback: treat as hourly interval
        logger.warning("croniter not installed, treating cron as 3600s interval")
        return (now or time.time()) + 3600

    base = now or time.time()
    import datetime

    dt = datetime.datetime.fromtimestamp(base)
    cron = croniter(cron_expr, dt)
    next_dt = cron.get_next(datetime.datetime)
    return next_dt.timestamp()


class AgentScheduler:
    """Schedules managed agent ticks based on cron/interval configs.

    Runs a background thread that checks for due agents and dispatches
    ticks to the executor.
    """

    def __init__(
        self,
        manager: AgentManager,
        executor: AgentExecutor | Any,
        tick_interval: float = 1.0,
        task_poll_interval: float = 5.0,
        event_bus: Any = None,
    ) -> None:
        self._manager = manager
        self._executor = executor
        self._tick_interval = tick_interval
        self._task_poll_interval = task_poll_interval
        self._bus = event_bus
        # agent_id -> {schedule_type, schedule_value, next_fire}
        self._agents: dict[str, dict] = {}
        self._backlog_last_fire: dict[str, float] = {}
        self._tick_counts: dict[str, int] = {}
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()

    @property
    def registered_agents(self) -> set[str]:
        with self._lock:
            return set(self._agents.keys())

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def register_agent(self, agent_id: str) -> None:
        """Register an agent for scheduling."""
        agent = self._manager.get_agent(agent_id)
        if agent is None:
            raise ValueError(f"Agent {agent_id} not found")

        config = agent.get("config", {})
        schedule_type = config.get("schedule_type", "manual")
        schedule_value = config.get("schedule_value", 0)

        now = time.time()
        if schedule_type == "cron":
            next_fire = _next_cron_fire(str(schedule_value), now)
        elif schedule_type == "interval":
            next_fire = now + float(schedule_value)
        else:
            next_fire = float("inf")  # Manual: never auto-fires

        with self._lock:
            self._agents[agent_id] = {
                "schedule_type": schedule_type,
                "schedule_value": schedule_value,
                "next_fire": next_fire,
            }

        logger.info(
            "Registered agent %s (%s), next fire: %s",
            agent_id,
            schedule_type,
            next_fire,
        )

    def deregister_agent(self, agent_id: str) -> None:
        """Remove an agent from scheduling."""
        with self._lock:
            self._agents.pop(agent_id, None)
        logger.info("Deregistered agent %s", agent_id)

    def start(self) -> None:
        """Start the scheduler background thread."""
        if self.is_running:
            return
        if self._bus:
            self._bus.subscribe(EventType.AGENT_TICK_END, self._on_tick_event)
            for event_type in (
                EventType.TASK_CREATED,
                EventType.TASK_COMPLETED,
                EventType.TASK_FAILED,
                EventType.APP_LOGIN,
                EventType.APP_LOGOFF,
                EventType.PROJECT_STARTED,
                EventType.PROJECT_COMPLETED,
            ):
                self._bus.subscribe(event_type, self._on_app_event)
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name="agent-scheduler"
        )
        self._thread.start()
        logger.info("Agent scheduler started")

    def stop(self) -> None:
        """Stop the scheduler background thread."""
        self._stop_event.set()
        if self._bus:
            self._bus.unsubscribe(EventType.AGENT_TICK_END, self._on_tick_event)
            for event_type in (
                EventType.TASK_CREATED,
                EventType.TASK_COMPLETED,
                EventType.TASK_FAILED,
                EventType.APP_LOGIN,
                EventType.APP_LOGOFF,
                EventType.PROJECT_STARTED,
                EventType.PROJECT_COMPLETED,
            ):
                self._bus.unsubscribe(event_type, self._on_app_event)
        if self._thread is not None:
            self._thread.join(timeout=10)
            self._thread = None
        logger.info("Agent scheduler stopped")

    def _loop(self) -> None:
        """Main scheduler loop."""
        last_reconcile = 0.0
        reconcile_interval = 30
        while not self._stop_event.is_set():
            try:
                self._check_due_agents()
                self._check_due_jobs()
                self._check_task_backlog()
                now = time.time()
                if now - last_reconcile >= reconcile_interval:
                    self._reconcile()
                    last_reconcile = now
            except Exception:
                logger.exception("Scheduler tick error")
            self._stop_event.wait(self._tick_interval)

    def _check_due_agents(self) -> None:
        """Check all registered agents and fire those that are due."""
        now = time.time()

        with self._lock:
            due = [
                (aid, info)
                for aid, info in self._agents.items()
                if info["next_fire"] <= now
            ]

        for agent_id, info in due:
            agent = self._manager.get_agent(agent_id)
            if agent is None or not self._agent_can_run(agent):
                continue

            logger.info("Firing tick for agent %s", agent_id)
            try:
                self._executor.execute_tick(agent_id)
            except Exception:
                logger.exception("Error executing tick for agent %s", agent_id)

            # Update next fire time
            with self._lock:
                if agent_id in self._agents:
                    if info["schedule_type"] == "cron":
                        self._agents[agent_id]["next_fire"] = _next_cron_fire(
                            str(info["schedule_value"]),
                            now,
                        )
                    elif info["schedule_type"] == "interval":
                        self._agents[agent_id]["next_fire"] = now + float(
                            info["schedule_value"]
                        )
                    # Manual: stays at inf

    def _agent_can_run(self, agent: dict[str, Any]) -> bool:
        return agent["status"] not in (
            "paused",
            "archived",
            "running",
            "budget_exceeded",
            "stalled",
            "error",
            "needs_attention",
        )

    def run_job_now(self, job_id: str) -> dict[str, Any]:
        """Materialize and execute a job immediately."""
        return self._fire_job(job_id, event={"source": "manual"})

    def _check_due_jobs(self) -> None:
        for job in self._manager.list_due_jobs():
            try:
                if not self._job_condition_satisfied(job):
                    self._manager.update_job(job["id"], trigger=job.get("trigger") or {})
                    continue
                self._fire_job(job["id"], event={"source": "schedule"})
            except Exception:
                logger.exception("Error firing job %s", job.get("id"))

    def _job_condition_satisfied(self, job: dict[str, Any]) -> bool:
        if job.get("job_type") != "if_this_then_that":
            return True
        trigger = job.get("trigger") or {}
        condition = str(trigger.get("condition") or "").strip().casefold()
        if condition in ("always", "true"):
            return True
        agent = self._manager.get_agent(job["agent_id"]) or {}
        if condition.startswith("agent.status"):
            expected = condition.split("==", 1)[-1].strip() if "==" in condition else ""
            return bool(expected and str(agent.get("status") or "").casefold() == expected)
        if condition == "has_runnable_task":
            return bool(self._manager.has_runnable_task(job["agent_id"]))
        # Unsupported predicates remain dormant until an allowlisted evaluator exists.
        return False

    def handle_app_event(self, event_name: str, payload: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        """Fire active IFTTT jobs whose trigger event matches ``event_name``."""
        name = str(event_name or "").strip()
        if not name:
            return []
        fired: list[dict[str, Any]] = []
        for job in self._manager.list_jobs(status="active"):
            if job.get("job_type") != "if_this_then_that":
                continue
            trigger = job.get("trigger") or {}
            wanted = str(trigger.get("event") or trigger.get("event_name") or "").strip()
            if wanted != name:
                continue
            fired.append(
                self._fire_job(
                    job["id"],
                    event={"source": "app_event", "event_name": name, "payload": payload or {}},
                )
            )
        return fired

    def _on_app_event(self, event: Any) -> None:
        raw_name = getattr(event, "event_type", "") or ""
        event_name = str(getattr(raw_name, "value", raw_name))
        try:
            self.handle_app_event(event_name, getattr(event, "data", {}) or {})
        except Exception:
            logger.exception("Failed handling app event %s", event_name)

    def _fire_job(self, job_id: str, event: dict[str, Any] | None = None) -> dict[str, Any]:
        job = self._manager.get_job(job_id)
        if job is None:
            raise ValueError(f"Job {job_id} not found")
        agent = self._manager.get_agent(job["agent_id"])
        if agent is None or not self._agent_can_run(agent):
            raise ValueError(f"Agent for job {job_id} cannot run")

        run = self._manager.start_job_run(job_id, event=event or {})
        task_id = None
        try:
            chief = self._manager.get_chief_agent()
            assigned_by = chief["id"] if chief else None
            task = self._manager.materialize_job_task(
                job_id,
                assigned_by_agent_id=assigned_by,
            )
            task_id = task["id"]
            self._executor.execute_tick(job["agent_id"])
            return self._manager.finish_job_run(
                run["id"],
                status="completed",
                task_id=task_id,
                summary="Job fired and agent execution was queued.",
            )
        except Exception as exc:
            self._manager.finish_job_run(
                run["id"],
                status="failed",
                task_id=task_id,
                error=str(exc),
            )
            raise

    def _check_task_backlog(self) -> None:
        """Keep idle agents moving while due uncompleted linked work exists."""
        now = time.time()
        for agent in self._manager.list_agents():
            agent_id = agent["id"]
            if not self._agent_can_run(agent):
                continue
            last_fire = self._backlog_last_fire.get(agent_id, 0.0)
            if now - last_fire < self._task_poll_interval:
                continue
            try:
                has_work = (
                    self._manager.has_runnable_task(agent_id)
                    if hasattr(self._manager, "has_runnable_task")
                    else False
                )
            except Exception:
                logger.exception("Failed checking runnable work for %s", agent_id)
                continue
            if not has_work:
                continue
            logger.info("Firing backlog tick for agent %s", agent_id)
            self._backlog_last_fire[agent_id] = now
            try:
                self._executor.execute_tick(agent_id)
            except Exception:
                logger.exception("Error executing backlog tick for agent %s", agent_id)

    def _reconcile(self) -> None:
        """Check running agents for stalls and handle retries."""
        agents = self._manager.list_agents()
        now = time.time()

        for agent in agents:
            if agent["status"] != "running":
                continue

            config = agent.get("config", {})
            timeout = config.get("timeout_seconds", 0)
            if timeout <= 0:
                continue

            last_activity = agent.get("last_activity_at")
            if last_activity is None:
                continue

            if now - last_activity <= timeout:
                continue

            # Agent is stalled
            max_retries = config.get("max_stall_retries", 5)
            current_retries = agent.get("stall_retries", 0)

            if current_retries >= max_retries:
                self._manager.update_agent(agent["id"], status="error")
                logger.warning(
                    "Agent %s stall retries exhausted (%d/%d), setting error",
                    agent["id"],
                    current_retries,
                    max_retries,
                )
            else:
                self._manager.end_tick(agent["id"])  # Release concurrency guard
                self._manager.update_agent(
                    agent["id"],
                    stall_retries=current_retries + 1,
                )
                if self._bus:
                    self._bus.publish(
                        EventType.AGENT_STALL_DETECTED,
                        {
                            "agent_id": agent["id"],
                            "last_activity_at": last_activity,
                            "stall_retries": current_retries + 1,
                        },
                    )
                logger.warning(
                    "Agent %s stalled (retry %d/%d)",
                    agent["id"],
                    current_retries + 1,
                    max_retries,
                )

    # -- Learning tick counting ------------------------------------------------

    def _on_tick_completed(self, agent_id: str) -> None:
        """Track completed ticks and trigger learning if schedule is met."""
        self._tick_counts[agent_id] = self._tick_counts.get(agent_id, 0) + 1

        agent = self._manager.get_agent(agent_id)
        if agent is None:
            return

        config = agent.get("config", {})
        if not config.get("learning_enabled", False):
            return

        schedule = config.get("learning_schedule", "every_20_ticks")
        if schedule.startswith("every_"):
            try:
                threshold = int(schedule.split("_")[1].replace("ticks", ""))
            except (IndexError, ValueError):
                threshold = 20
        else:
            return

        if self._tick_counts[agent_id] >= threshold:
            self._tick_counts[agent_id] = 0
            if self._bus:
                self._bus.publish(
                    EventType.AGENT_LEARNING_STARTED,
                    {
                        "agent_id": agent_id,
                    },
                )
            logger.info(
                "Learning triggered for agent %s after %d ticks",
                agent_id,
                threshold,
            )

    def _on_tick_event(self, event: Any) -> None:
        """Handle AGENT_TICK_END to count ticks."""
        agent_id = event.data.get("agent_id")
        if agent_id and event.data.get("status") == "ok":
            self._on_tick_completed(agent_id)
