"""Internal routing for Watchtower findings."""

from __future__ import annotations

import json
import time
from typing import Any

from openjarvis.watchtower.store import WatchtowerStore
from openjarvis.watchtower.types import (
    InternalRoute,
    Priority,
    WatchtowerFinding,
    WatchtowerSettings,
)

_MESSAGE_TYPE_BY_FINDING = {
    "overdue_task": "deadline_warning",
    "due_soon_task": "deadline_warning",
    "blocked_task": "blocker_check",
    "blocked_agent": "blocker_check",
    "stale_approval": "approval_needed",
    "project_at_risk": "timeline_risk_check",
    "job_failed": "system_failure_notice",
}


class InternalRouter:
    def __init__(
        self,
        store: WatchtowerStore,
        agent_manager: Any = None,
        settings: WatchtowerSettings | None = None,
    ) -> None:
        self.store = store
        self.agent_manager = agent_manager
        self.settings = settings or WatchtowerSettings()

    def route_to_chief(self, finding: WatchtowerFinding) -> InternalRoute | None:
        if self.agent_manager is None:
            return None
        chief = self.agent_manager.get_chief_agent()
        if not chief:
            return None
        recent = self.store.get_recent_internal_route(
            finding_id=finding.finding_id,
            route_type="send_to_chief",
            to_agent_id=chief["id"],
            cooldown_seconds=self.settings.default_cooldown_minutes * 60,
        )
        if recent is not None:
            return recent
        message_type = _MESSAGE_TYPE_BY_FINDING.get(
            finding.finding_type,
            "status_request",
        )
        response_due_at = time.time() + self.settings.internal_response_minutes * 60
        route = self.store.create_internal_route(
            finding_id=finding.finding_id,
            to_agent_id=chief["id"],
            route_type="send_to_chief",
            priority=finding.priority,
            message_type=message_type,
            requires_response=True,
            response_due_at=response_due_at,
            metadata={
                "source": "watchtower",
                "finding_id": finding.finding_id,
                "finding_type": finding.finding_type,
                "entity_type": finding.entity_type,
                "entity_id": finding.entity_id,
                "project_id": finding.project_id,
                "task_id": finding.task_id,
                "agent_id": finding.agent_id,
            },
        )
        body = self._chief_message(finding, route, message_type)
        self.agent_manager.send_message(chief["id"], body, mode="queued")
        self.store.update_internal_route_status(route.route_id, "sent")
        return self.store.get_internal_route(route.route_id)

    @staticmethod
    def _chief_message(
        finding: WatchtowerFinding,
        route: InternalRoute,
        message_type: str,
    ) -> str:
        payload = {
            "source": "watchtower",
            "finding_id": finding.finding_id,
            "route_id": route.route_id,
            "route_type": route.route_type,
            "message_type": message_type,
            "priority": finding.priority.value,
            "requires_user_notification": finding.priority
            in (Priority.URGENT, Priority.EMERGENCY),
            "requires_response": route.requires_response,
            "response_due_at": route.response_due_at,
            "project_id": finding.project_id,
            "task_id": finding.task_id,
            "agent_id": finding.agent_id,
            "summary": finding.reason,
            "recommended_action": finding.recommended_action,
            "metadata": finding.metadata,
        }
        return (
            "Watchtower-triggered internal route.\n"
            "Chief Orchestrator should handle this through the hierarchy and "
            "only escalate to the user if needed.\n\n"
            f"{json.dumps(payload, sort_keys=True)}"
        )
