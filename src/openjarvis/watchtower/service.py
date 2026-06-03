"""Watchtower background service and scan orchestration."""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Dict, List

from openjarvis.core.events import EventType
from openjarvis.watchtower.internal_router import InternalRouter
from openjarvis.watchtower.local_reasoner import LocalReasoner
from openjarvis.watchtower.notifier import WatchtowerNotifier
from openjarvis.watchtower.rules import WatchtowerRules
from openjarvis.watchtower.store import WatchtowerStore
from openjarvis.watchtower.types import Priority, WatchtowerFinding, WatchtowerSettings

logger = logging.getLogger(__name__)


class WatchtowerService:
    def __init__(
        self,
        *,
        store: WatchtowerStore,
        settings: WatchtowerSettings | None = None,
        project_store: Any = None,
        agent_manager: Any = None,
        approval_store: Any = None,
        event_bus: Any = None,
        telegram_channel: Any = None,
        telegram_chat_id: str = "",
        provider_config: Any = None,
        engine: Any = None,
    ) -> None:
        self.store = store
        self.settings = settings or WatchtowerSettings.from_dict(store.get_settings())
        self.project_store = project_store
        self.agent_manager = agent_manager
        self.approval_store = approval_store
        self.event_bus = event_bus
        self.rules = WatchtowerRules(self.settings)
        self.reasoner = LocalReasoner(provider_config=provider_config, engine=engine)
        self.internal_router = InternalRouter(store, agent_manager, self.settings)
        self.notifier = WatchtowerNotifier(
            store,
            self.settings,
            event_bus=event_bus,
            telegram_channel=telegram_channel,
            telegram_chat_id=telegram_chat_id,
        )
        self.last_scan_at: float | None = None
        self.last_error: str = ""
        self.local_ai_status = "rules_fallback"
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self.is_running or not self.settings.enabled:
            return
        self._subscribe_events()
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name="watchtower"
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=10)
            self._thread = None

    def status(self) -> Dict[str, Any]:
        active_findings = len(self.store.list_findings(status="active", limit=500))
        pending_routes = len(self.store.list_internal_routes(status="sent", limit=500))
        return {
            "enabled": self.settings.enabled,
            "running": self.is_running,
            "last_scan_at": self.last_scan_at,
            "last_error": self.last_error,
            "local_ai_status": self.local_ai_status,
            "dnd_enabled": self.settings.dnd_enabled,
            "telegram_enabled": self.settings.telegram_enabled,
            "active_findings": active_findings,
            "pending_internal_routes": pending_routes,
        }

    def scan_once(self) -> Dict[str, Any]:
        started = time.time()
        raw_findings = self._collect_rule_findings(now_ts=started)
        persisted: list[WatchtowerFinding] = []
        for raw in raw_findings:
            reasoning = self.reasoner.reason(raw)
            self.local_ai_status = reasoning["decision"]
            finding = self.store.upsert_finding(
                finding_type=raw["finding_type"],
                entity_type=raw["entity_type"],
                entity_id=raw["entity_id"],
                project_id=raw.get("project_id"),
                task_id=raw.get("task_id"),
                agent_id=raw.get("agent_id"),
                priority=raw.get("priority") or Priority.INFO,
                reason=reasoning["summary"],
                recommended_action=reasoning["recommended_action"],
                metadata={
                    **(raw.get("metadata") or {}),
                    "local_ai_decision": reasoning["decision"],
                },
            )
            persisted.append(finding)
            self._route_finding(finding)
        self.last_scan_at = time.time()
        self.last_error = ""
        return {
            "started_at": started,
            "finished_at": self.last_scan_at,
            "findings_detected": len(raw_findings),
            "findings": [finding.to_dict() for finding in persisted],
            "local_ai_status": self.local_ai_status,
        }

    def route_to_chief(self, finding_id: str) -> Dict[str, Any]:
        finding = self.store.get_finding(finding_id)
        if finding is None:
            raise KeyError(finding_id)
        route = self.internal_router.route_to_chief(finding)
        return route.to_dict() if route else {"status": "no_chief_configured"}

    def _route_finding(self, finding: WatchtowerFinding) -> None:
        self.internal_router.route_to_chief(finding)
        if finding.priority in (Priority.URGENT, Priority.EMERGENCY):
            self.notifier.notify(finding)
        elif finding.finding_type == "stale_approval":
            self.notifier.notify(finding)

    def _collect_rule_findings(self, *, now_ts: float) -> List[Dict[str, Any]]:
        findings: list[dict[str, Any]] = []
        if self.project_store is not None:
            try:
                findings.extend(
                    self.rules.scan_project_bundle(
                        self.project_store.list_projects_with_tasks()
                    )
                )
            except Exception:
                logger.exception("Watchtower project scan failed")
        if self.agent_manager is not None:
            try:
                findings.extend(
                    self.rules.scan_agents(
                        self.agent_manager.list_agents(), now_ts=now_ts
                    )
                )
                findings.extend(
                    self.rules.scan_job_runs(
                        self.agent_manager.list_jobs(), self.agent_manager
                    )
                )
            except Exception:
                logger.exception("Watchtower agent scan failed")
        if self.approval_store is not None:
            try:
                findings.extend(
                    self.rules.scan_approvals(
                        self.approval_store.list(state="pending"), now_ts=now_ts
                    )
                )
            except Exception:
                logger.exception("Watchtower approval scan failed")
        return findings

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.scan_once()
            except Exception as exc:
                self.last_error = str(exc)
                logger.exception("Watchtower scan failed")
            self._stop.wait(max(5, self.settings.loop_interval_seconds))

    def _subscribe_events(self) -> None:
        if self.event_bus is None:
            return
        for event_type in (
            EventType.TASK_CREATED,
            EventType.TASK_UPDATED,
            EventType.TASK_COMPLETED,
            EventType.TASK_FAILED,
            EventType.APPROVAL_REQUESTED,
            EventType.APPROVAL_RESOLVED,
            EventType.JOB_FAILED,
            EventType.AGENT_STALL_DETECTED,
            EventType.AGENT_TICK_ERROR,
            EventType.SECURITY_ALERT,
            EventType.SECURITY_BLOCK,
        ):
            try:
                self.event_bus.subscribe(event_type, self._on_event)
            except Exception:
                pass

    def _on_event(self, event: Any) -> None:
        if getattr(event, "event_type", None) in {
            EventType.SECURITY_ALERT,
            EventType.SECURITY_BLOCK,
        }:
            data = getattr(event, "data", {}) or {}
            self.store.upsert_finding(
                finding_type="security_issue",
                entity_type="system_event",
                entity_id=str(
                    data.get("id") or getattr(event, "timestamp", time.time())
                ),
                priority=Priority.EMERGENCY,
                reason=str(data.get("message") or "Security event detected."),
                recommended_action="Notify Chief and user immediately.",
                metadata={"event": data},
            )
