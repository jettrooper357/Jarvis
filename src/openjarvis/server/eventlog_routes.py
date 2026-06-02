"""Read-only REST routes for the persisted event log."""

from __future__ import annotations

import datetime
from typing import Any, Dict, Optional

from fastapi import APIRouter, Request

from openjarvis.eventlog.store import EventRecord

eventlog_router = APIRouter(prefix="/v1/events", tags=["events"])


def _serialise_event(record: EventRecord) -> Dict[str, Any]:
    created = (
        datetime.datetime.fromtimestamp(
            record.timestamp, tz=datetime.timezone.utc
        ).isoformat()
        if record.timestamp
        else None
    )
    return {
        "id": record.id,
        "event_type": record.event_type,
        "timestamp": record.timestamp,
        "created_at": created,
        "agent_id": record.agent_id,
        "task_id": record.task_id,
        "project_id": record.project_id,
        "run_id": record.run_id,
        "data": record.data,
    }


@eventlog_router.get("")
async def list_events(
    request: Request,
    event_type: Optional[str] = None,
    agent_id: Optional[str] = None,
    task_id: Optional[str] = None,
    project_id: Optional[str] = None,
    run_id: Optional[str] = None,
    since: Optional[float] = None,
    until: Optional[float] = None,
    limit: int = 100,
):
    """List events with optional filters."""
    store = getattr(request.app.state, "event_log_store", None)
    if store is None:
        return {"events": []}
    records = store.query(
        event_type=event_type,
        agent_id=agent_id,
        task_id=task_id,
        project_id=project_id,
        run_id=run_id,
        since=since,
        until=until,
        limit=limit,
    )
    return {"events": [_serialise_event(r) for r in records]}


@eventlog_router.get("/feed")
async def event_feed(request: Request, limit: int = 50, since: Optional[float] = None):
    """Newest-first activity feed across all event types."""
    store = getattr(request.app.state, "event_log_store", None)
    if store is None:
        return {"events": []}
    records = store.feed(limit=limit, since=since)
    return {"events": [_serialise_event(r) for r in records]}
