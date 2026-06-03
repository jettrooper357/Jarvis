"""Do-not-disturb policy for user notifications."""

from __future__ import annotations

from datetime import datetime, time

from openjarvis.watchtower.types import DndDecision, Priority, WatchtowerSettings


def _parse_hhmm(value: str) -> time:
    hour, minute = str(value or "00:00").split(":", 1)
    return time(hour=int(hour), minute=int(minute[:2]))


def _in_quiet_hours(now: datetime, start: str, end: str) -> bool:
    start_t = _parse_hhmm(start)
    end_t = _parse_hhmm(end)
    current = now.time()
    if start_t <= end_t:
        return start_t <= current < end_t
    return current >= start_t or current < end_t


class DoNotDisturbPolicy:
    def __init__(self, settings: WatchtowerSettings) -> None:
        self.settings = settings

    def is_active(self, now: datetime | None = None) -> bool:
        if not self.settings.dnd_enabled:
            return False
        current = now or datetime.now()
        return _in_quiet_hours(
            current,
            self.settings.quiet_hours_start,
            self.settings.quiet_hours_end,
        )

    def decide(
        self, priority: Priority | str, now: datetime | None = None
    ) -> DndDecision:
        pri = priority if isinstance(priority, Priority) else Priority(str(priority))
        if not self.is_active(now):
            return DndDecision.ALLOW
        if pri is Priority.EMERGENCY and self.settings.allow_emergency_bypass:
            return DndDecision.BYPASS
        if pri is Priority.URGENT:
            return (
                DndDecision.BYPASS
                if self.settings.allow_urgent_bypass
                else DndDecision.DEFER
            )
        if pri is Priority.HIGH:
            return (
                DndDecision.DEFER
                if self.settings.defer_high_priority
                else DndDecision.ALLOW
            )
        if pri is Priority.NORMAL:
            return (
                DndDecision.DEFER
                if self.settings.defer_normal_priority
                else DndDecision.ALLOW
            )
        if pri in (Priority.LOW, Priority.INFO):
            return (
                DndDecision.DEFER
                if self.settings.defer_low_priority
                else DndDecision.ALLOW
            )
        return DndDecision.DEFER
