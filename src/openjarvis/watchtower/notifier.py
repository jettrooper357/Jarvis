"""User notification routing for Watchtower."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from openjarvis.core.events import EventType
from openjarvis.watchtower.dnd import DoNotDisturbPolicy
from openjarvis.watchtower.priority import priority_at_least
from openjarvis.watchtower.store import WatchtowerStore
from openjarvis.watchtower.types import (
    DndDecision,
    NotificationRoute,
    Priority,
    WatchtowerFinding,
    WatchtowerSettings,
)

_SECRET_PATTERNS = (
    re.compile(r"(?i)(api[_-]?key|token|secret|password)\s*[:=]\s*['\"]?[^'\"\s]+"),
    re.compile(r"(?i)bearer\s+[a-z0-9._\-]+"),
)


def sanitize_notification(text: str) -> str:
    cleaned = str(text or "")
    for pattern in _SECRET_PATTERNS:
        cleaned = pattern.sub("[redacted]", cleaned)
    return cleaned[:1200]


class WatchtowerNotifier:
    def __init__(
        self,
        store: WatchtowerStore,
        settings: WatchtowerSettings,
        *,
        event_bus: Any = None,
        telegram_channel: Any = None,
        telegram_chat_id: str = "",
        speech: Any = None,
    ) -> None:
        self.store = store
        self.settings = settings
        self.event_bus = event_bus
        self.telegram_channel = telegram_channel
        self.telegram_chat_id = telegram_chat_id
        self.speech = speech

    def decide_route(self, finding: WatchtowerFinding) -> NotificationRoute:
        pri = finding.priority
        if pri in (Priority.INFO, Priority.LOW):
            return NotificationRoute.DIGEST_LATER
        wants_telegram = self.settings.telegram_enabled and priority_at_least(
            pri, self.settings.telegram_min_priority
        )
        wants_in_app = self.settings.in_app_enabled and priority_at_least(
            pri, self.settings.in_app_min_priority
        )
        wants_both = priority_at_least(pri, self.settings.both_min_priority)
        if wants_both and wants_in_app and wants_telegram:
            return NotificationRoute.BOTH_USER
        if wants_telegram:
            return NotificationRoute.TELEGRAM_USER
        if wants_in_app:
            return NotificationRoute.IN_APP_USER
        return NotificationRoute.NONE

    def notify(
        self, finding: WatchtowerFinding, *, now: datetime | None = None
    ) -> dict[str, Any]:
        route = self.decide_route(finding)
        issue = finding.finding_type.replace("_", " ")
        title = sanitize_notification(
            f"[{finding.priority.value.upper()}] Jarvis Watchtower: {issue}"
        )
        body = sanitize_notification(
            f"{finding.reason}\n\nWhy it matters: {finding.recommended_action}\n"
            f"Reference: {finding.entity_type} {finding.entity_id}"
        )
        if route in (NotificationRoute.NONE, NotificationRoute.DIGEST_LATER):
            return self.store.record_notification(
                finding_id=finding.finding_id,
                priority=finding.priority,
                route=route.value,
                title=title,
                body=body,
                decision="deferred"
                if route is NotificationRoute.DIGEST_LATER
                else "suppressed",
            )
        dnd = DoNotDisturbPolicy(self.settings)
        dnd_decision = dnd.decide(finding.priority, now=now)
        if dnd_decision is DndDecision.DEFER:
            return self.store.record_notification(
                finding_id=finding.finding_id,
                priority=finding.priority,
                route=route.value,
                title=title,
                body=body,
                decision="deferred",
                dnd_applied=True,
            )
        sent = True
        error = None
        try:
            if route in (NotificationRoute.IN_APP_USER, NotificationRoute.BOTH_USER):
                self._send_in_app(finding, title, body)
            if route in (NotificationRoute.TELEGRAM_USER, NotificationRoute.BOTH_USER):
                sent = self._send_telegram(title, body)
                if not sent:
                    error = "telegram_send_failed"
            if self.speech is not None:
                self.speech.speak(finding)
        except Exception as exc:  # pragma: no cover - defensive
            sent = False
            error = str(exc)
        return self.store.record_notification(
            finding_id=finding.finding_id,
            priority=finding.priority,
            route=route.value,
            title=title,
            body=body,
            decision="sent" if sent else "failed",
            dnd_applied=dnd_decision is not DndDecision.ALLOW,
            bypassed_dnd=dnd_decision is DndDecision.BYPASS,
            error_message=error,
        )

    def _send_in_app(self, finding: WatchtowerFinding, title: str, body: str) -> None:
        if self.event_bus is None:
            return
        self.event_bus.publish(
            EventType.UI_NOTIFICATION,
            {
                "source": "watchtower",
                "finding_id": finding.finding_id,
                "priority": finding.priority.value,
                "title": title,
                "body": body,
            },
        )

    def _send_telegram(self, title: str, body: str) -> bool:
        if self.telegram_channel is None or not self.telegram_chat_id:
            return False
        return bool(
            self.telegram_channel.send(
                self.telegram_chat_id,
                f"{title}\n\n{body}",
                conversation_id=self.telegram_chat_id,
                metadata={"source": "watchtower"},
            )
        )
