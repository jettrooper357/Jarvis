"""Deterministic Watchtower priority classification."""

from __future__ import annotations

from openjarvis.watchtower.types import PRIORITY_ORDER, Priority


def priority_at_least(value: Priority | str, minimum: Priority | str) -> bool:
    left = value if isinstance(value, Priority) else Priority(str(value))
    right = minimum if isinstance(minimum, Priority) else Priority(str(minimum))
    return PRIORITY_ORDER[left] >= PRIORITY_ORDER[right]


class PriorityEngine:
    """Classify findings without requiring AI."""

    def classify(self, finding_type: str, metadata: dict | None = None) -> Priority:
        data = metadata or {}
        ftype = str(finding_type or "").strip().lower()
        if ftype in {"security_issue", "critical_system_failure"}:
            return Priority.EMERGENCY
        if ftype in {
            "milestone_at_risk",
            "user_approval_blocking",
            "critical_deadline_missed",
        }:
            return Priority.URGENT
        if ftype in {
            "overdue_task",
            "blocked_agent",
            "blocked_task",
            "stale_approval",
            "job_failed",
        }:
            return Priority.HIGH
        if ftype in {"due_soon_task", "task_waiting", "stale_task", "project_at_risk"}:
            return Priority.NORMAL
        if data.get("completed"):
            return Priority.LOW
        return Priority.INFO

    def escalate(self, current: Priority, proposed: Priority) -> Priority:
        return proposed if priority_at_least(proposed, current) else current
