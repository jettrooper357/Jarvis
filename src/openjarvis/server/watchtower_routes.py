"""FastAPI routes for Jarvis Watchtower."""

from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from openjarvis.watchtower.types import Priority, WatchtowerSettings


class SnoozeRequest(BaseModel):
    minutes: int = 30


class ResolveRequest(BaseModel):
    reason: Optional[str] = None


class EscalateRequest(BaseModel):
    reason: str = "manual escalation"


class TestNotificationRequest(BaseModel):
    priority: str = "normal"
    route: Optional[str] = None


class TestChannelRequest(BaseModel):
    priority: str = "high"


class SpeakAgainRequest(BaseModel):
    finding_id: str


class RouteToChiefRequest(BaseModel):
    finding_id: str


_SETTING_KEYS = set(WatchtowerSettings().__dataclass_fields__)  # type: ignore[attr-defined]
_PRIORITY_SETTING_KEYS = {
    "in_app_min_priority",
    "telegram_min_priority",
    "both_min_priority",
}


def _store(request: Request):
    store = getattr(request.app.state, "watchtower_store", None)
    if store is None:
        raise HTTPException(503, "Watchtower store is not available")
    return store


def _service(request: Request):
    service = getattr(request.app.state, "watchtower_service", None)
    if service is None:
        raise HTTPException(503, "Watchtower service is not available")
    return service


def _settings_from_store(request: Request) -> WatchtowerSettings:
    return WatchtowerSettings.from_dict(_store(request).get_settings())


def _validate_settings_patch(body: Dict[str, Any]) -> Dict[str, Any]:
    clean: Dict[str, Any] = {}
    for key, value in body.items():
        if key not in _SETTING_KEYS:
            raise HTTPException(400, f"Unknown Watchtower setting: {key}")
        if key in _PRIORITY_SETTING_KEYS:
            try:
                value = Priority(str(value)).value
            except ValueError:
                raise HTTPException(400, f"Invalid priority for {key}: {value}")
        if key.endswith(("_seconds", "_minutes", "_hours")):
            value = int(value)
            if value < 0:
                raise HTTPException(400, f"{key} must be non-negative")
        clean[key] = value
    return clean


def create_watchtower_router() -> APIRouter:
    router = APIRouter(prefix="/v1/watchtower", tags=["watchtower"])

    @router.get("/status")
    async def status(request: Request):
        return _service(request).status()

    @router.get("/brief")
    async def brief(request: Request):
        return _service(request).brief()

    @router.get("/notifications")
    async def notifications(
        request: Request,
        finding_id: Optional[str] = None,
        decision: Optional[str] = None,
        limit: int = 100,
    ):
        return {
            "notifications": _store(request).list_notifications(
                finding_id=finding_id,
                decision=decision,
                limit=limit,
            )
        }

    @router.get("/speech-events")
    async def speech_events(
        request: Request,
        finding_id: Optional[str] = None,
        limit: int = 100,
    ):
        return {
            "speech_events": _store(request).list_speech_events(
                finding_id=finding_id,
                limit=limit,
            )
        }

    @router.get("/findings")
    async def findings(
        request: Request,
        status: Optional[str] = None,
        priority: Optional[str] = None,
        limit: int = 100,
    ):
        return {
            "findings": [
                finding.to_dict()
                for finding in _store(request).list_findings(
                    status=status,
                    priority=priority,
                    limit=limit,
                )
            ]
        }

    @router.get("/findings/{finding_id}")
    async def finding(finding_id: str, request: Request):
        found = _store(request).get_finding(finding_id)
        if found is None:
            raise HTTPException(404, f"Finding not found: {finding_id}")
        return found.to_dict()

    @router.post("/findings/{finding_id}/snooze")
    async def snooze_finding(
        finding_id: str,
        body: SnoozeRequest,
        request: Request,
    ):
        found = _store(request).update_finding_status(finding_id, "snoozed")
        return {**found.to_dict(), "snooze_minutes": body.minutes}

    @router.post("/findings/{finding_id}/resolve")
    async def resolve_finding(
        finding_id: str,
        body: ResolveRequest,
        request: Request,
    ):
        found = _store(request).update_finding_status(finding_id, "resolved")
        return {**found.to_dict(), "reason": body.reason}

    @router.post("/findings/{finding_id}/escalate")
    async def escalate_finding(
        finding_id: str,
        body: EscalateRequest,
        request: Request,
    ):
        store = _store(request)
        found = store.get_finding(finding_id)
        if found is None:
            raise HTTPException(404, f"Finding not found: {finding_id}")
        escalation = store.record_escalation(
            finding_id=finding_id,
            escalation_reason=body.reason,
        )
        return {"finding": found.to_dict(), "escalation": escalation}

    @router.get("/internal-routes")
    async def internal_routes(
        request: Request,
        status: Optional[str] = None,
        limit: int = 100,
    ):
        return {
            "routes": [
                route.to_dict()
                for route in _store(request).list_internal_routes(
                    status=status,
                    limit=limit,
                )
            ]
        }

    @router.get("/internal-routes/{route_id}")
    async def internal_route(route_id: str, request: Request):
        route = _store(request).get_internal_route(route_id)
        if route is None:
            raise HTTPException(404, f"Internal route not found: {route_id}")
        return route.to_dict()

    @router.post("/internal-routes/{route_id}/resolve")
    async def resolve_internal_route(route_id: str, request: Request):
        return (
            _store(request)
            .update_internal_route_status(
                route_id,
                "resolved",
            )
            .to_dict()
        )

    @router.post("/internal-routes/{route_id}/escalate")
    async def escalate_internal_route(
        route_id: str,
        body: EscalateRequest,
        request: Request,
    ):
        store = _store(request)
        route = store.update_internal_route_status(route_id, "escalated")
        escalation = store.record_escalation(
            finding_id=route.finding_id,
            route_id=route_id,
            escalation_reason=body.reason,
        )
        return {"route": route.to_dict(), "escalation": escalation}

    @router.get("/settings")
    async def settings(request: Request):
        return _settings_from_store(request).to_dict()

    @router.patch("/settings")
    async def patch_settings(body: Dict[str, Any], request: Request):
        updates = _validate_settings_patch(body or {})
        merged = _store(request).patch_settings(updates)
        return WatchtowerSettings.from_dict(merged).to_dict()

    @router.post("/scan-now")
    async def scan_now(request: Request):
        return _service(request).scan_once()

    @router.post("/test-notification")
    async def test_notification(
        body: TestNotificationRequest,
        request: Request,
    ):
        service = _service(request)
        priority = Priority(str(body.priority))
        finding = _store(request).upsert_finding(
            finding_type="test_notification",
            entity_type="system",
            entity_id="watchtower-test",
            priority=priority,
            reason="This is a harmless Watchtower test notification.",
            recommended_action="No action required.",
            metadata={"test": True, "requested_route": body.route},
        )
        return service.notifier.notify(finding)

    @router.post("/test-telegram")
    async def test_telegram(body: TestChannelRequest, request: Request):
        return _service(request).test_telegram(Priority(str(body.priority)))

    @router.post("/test-speech")
    async def test_speech(body: TestChannelRequest, request: Request):
        return _service(request).test_speech(Priority(str(body.priority)))

    @router.post("/speak-again")
    async def speak_again(body: SpeakAgainRequest, request: Request):
        try:
            return _service(request).speak_again(body.finding_id)
        except KeyError:
            raise HTTPException(404, f"Finding not found: {body.finding_id}")

    @router.post("/route-to-chief")
    async def route_to_chief(body: RouteToChiefRequest, request: Request):
        try:
            return _service(request).route_to_chief(body.finding_id)
        except KeyError:
            raise HTTPException(404, f"Finding not found: {body.finding_id}")

    return router
