"""Optional spoken alerts for Watchtower."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from openjarvis.watchtower.dnd import DoNotDisturbPolicy
from openjarvis.watchtower.notifier import sanitize_notification
from openjarvis.watchtower.priority import priority_at_least
from openjarvis.watchtower.store import WatchtowerStore
from openjarvis.watchtower.types import (
    DndDecision,
    Priority,
    WatchtowerFinding,
    WatchtowerSettings,
)


class WatchtowerSpeech:
    def __init__(
        self,
        store: WatchtowerStore,
        settings: WatchtowerSettings,
        *,
        tts_backend: Any = None,
    ) -> None:
        self.store = store
        self.settings = settings
        self.tts_backend = tts_backend

    def should_speak(self, priority: Priority | str) -> bool:
        pri = priority if isinstance(priority, Priority) else Priority(str(priority))
        if not self.settings.speech_enabled:
            return False
        if pri is Priority.NORMAL and not self.settings.speak_normal_priority:
            return False
        if pri is Priority.HIGH and not self.settings.speak_high_priority:
            return False
        return priority_at_least(pri, self.settings.speech_min_priority)

    def speech_text(self, finding: WatchtowerFinding) -> str:
        issue = finding.finding_type.replace("_", " ")
        return sanitize_notification(
            f"Jarvis Watchtower alert. {issue}. {finding.reason} "
            f"{finding.recommended_action}"
        )[:320]

    def speak(
        self,
        finding: WatchtowerFinding,
        *,
        text: str | None = None,
        force: bool = False,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        spoken_text = sanitize_notification(text or self.speech_text(finding))[:320]
        dnd_decision = DoNotDisturbPolicy(self.settings).decide(
            finding.priority,
            now=now,
        )
        if not force:
            if not self.should_speak(finding.priority):
                return self.store.record_speech_event(
                    finding_id=finding.finding_id,
                    priority=finding.priority,
                    text_spoken=spoken_text,
                    success=False,
                    error_message="speech_priority_suppressed",
                )
            if dnd_decision is DndDecision.DEFER:
                return self.store.record_speech_event(
                    finding_id=finding.finding_id,
                    priority=finding.priority,
                    text_spoken=spoken_text,
                    success=False,
                    dnd_applied=True,
                    error_message="speech_deferred_by_dnd",
                )
        if self.tts_backend is None:
            return self.store.record_speech_event(
                finding_id=finding.finding_id,
                priority=finding.priority,
                text_spoken=spoken_text,
                success=False,
                dnd_applied=dnd_decision is not DndDecision.ALLOW,
                bypassed_dnd=dnd_decision is DndDecision.BYPASS,
                error_message="tts_backend_not_configured",
            )
        try:
            self.tts_backend.synthesize(spoken_text, output_format="wav")
            return self.store.record_speech_event(
                finding_id=finding.finding_id,
                priority=finding.priority,
                text_spoken=spoken_text,
                success=True,
                dnd_applied=dnd_decision is not DndDecision.ALLOW,
                bypassed_dnd=dnd_decision is DndDecision.BYPASS,
                metadata={
                    "tts_backend": getattr(self.tts_backend, "backend_id", "unknown")
                },
            )
        except Exception as exc:
            return self.store.record_speech_event(
                finding_id=finding.finding_id,
                priority=finding.priority,
                text_spoken=spoken_text,
                success=False,
                dnd_applied=dnd_decision is not DndDecision.ALLOW,
                bypassed_dnd=dnd_decision is DndDecision.BYPASS,
                error_message=str(exc),
            )
