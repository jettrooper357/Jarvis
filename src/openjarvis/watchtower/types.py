"""Types for Jarvis Watchtower."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional


class Priority(str, Enum):
    INFO = "info"
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"
    EMERGENCY = "emergency"


PRIORITY_ORDER: dict[Priority, int] = {
    Priority.INFO: 0,
    Priority.LOW: 1,
    Priority.NORMAL: 2,
    Priority.HIGH: 3,
    Priority.URGENT: 4,
    Priority.EMERGENCY: 5,
}


class NotificationRoute(str, Enum):
    NONE = "none"
    IN_APP_USER = "in_app_user"
    TELEGRAM_USER = "telegram_user"
    BOTH_USER = "both_user"
    DIGEST_LATER = "digest_later"


class DndDecision(str, Enum):
    ALLOW = "allow"
    DEFER = "defer"
    SUPPRESS = "suppress"
    BYPASS = "bypass"


@dataclass(slots=True)
class WatchtowerFinding:
    finding_id: str
    finding_type: str
    entity_type: str
    entity_id: str
    priority: Priority
    status: str = "active"
    reason: str = ""
    recommended_action: str = ""
    project_id: Optional[str] = None
    task_id: Optional[str] = None
    agent_id: Optional[str] = None
    created_at: float = 0.0
    updated_at: float = 0.0
    resolved_at: Optional[float] = None
    last_notified_at: Optional[float] = None
    notification_count: int = 0
    dedupe_key: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "finding_id": self.finding_id,
            "finding_type": self.finding_type,
            "entity_type": self.entity_type,
            "entity_id": self.entity_id,
            "project_id": self.project_id,
            "task_id": self.task_id,
            "agent_id": self.agent_id,
            "priority": self.priority.value,
            "status": self.status,
            "reason": self.reason,
            "recommended_action": self.recommended_action,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "resolved_at": self.resolved_at,
            "last_notified_at": self.last_notified_at,
            "notification_count": self.notification_count,
            "dedupe_key": self.dedupe_key,
            "metadata": dict(self.metadata),
        }


@dataclass(slots=True)
class InternalRoute:
    route_id: str
    finding_id: str
    source: str
    from_agent_id: str
    to_agent_id: str
    route_type: str
    priority: Priority
    message_type: str
    requires_response: bool = True
    response_due_at: Optional[float] = None
    status: str = "pending"
    created_at: float = 0.0
    responded_at: Optional[float] = None
    escalated_at: Optional[float] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "route_id": self.route_id,
            "finding_id": self.finding_id,
            "source": self.source,
            "from_agent_id": self.from_agent_id,
            "to_agent_id": self.to_agent_id,
            "route_type": self.route_type,
            "priority": self.priority.value,
            "message_type": self.message_type,
            "requires_response": self.requires_response,
            "response_due_at": self.response_due_at,
            "status": self.status,
            "created_at": self.created_at,
            "responded_at": self.responded_at,
            "escalated_at": self.escalated_at,
            "metadata": dict(self.metadata),
        }


@dataclass(slots=True)
class WatchtowerSettings:
    enabled: bool = True
    loop_interval_seconds: int = 60
    local_ai_only: bool = True
    local_model_required: bool = True
    fallback_to_rules_if_local_ai_unavailable: bool = True
    dnd_enabled: bool = True
    quiet_hours_start: str = "22:00"
    quiet_hours_end: str = "07:00"
    timezone: str = "local"
    allow_emergency_bypass: bool = True
    allow_urgent_bypass: bool = False
    defer_low_priority: bool = True
    defer_normal_priority: bool = True
    defer_high_priority: bool = False
    in_app_enabled: bool = True
    telegram_enabled: bool = True
    in_app_min_priority: Priority = Priority.INFO
    telegram_min_priority: Priority = Priority.HIGH
    both_min_priority: Priority = Priority.URGENT
    default_cooldown_minutes: int = 30
    emergency_cooldown_minutes: int = 5
    digest_interval_minutes: int = 60
    due_soon_hours: int = 24
    stale_task_hours: int = 24
    stale_agent_minutes: int = 30
    approval_stale_minutes: int = 30
    internal_response_minutes: int = 30

    def to_dict(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {}
        for field_name in self.__dataclass_fields__:  # type: ignore[attr-defined]
            value = getattr(self, field_name)
            out[field_name] = value.value if isinstance(value, Enum) else value
        return out

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "WatchtowerSettings":
        normalized = dict(data)
        for key in (
            "in_app_min_priority",
            "telegram_min_priority",
            "both_min_priority",
        ):
            if key in normalized and not isinstance(normalized[key], Priority):
                normalized[key] = Priority(str(normalized[key]))
        return cls(
            **{k: v for k, v in normalized.items() if k in cls.__dataclass_fields__}
        )  # type: ignore[attr-defined]
