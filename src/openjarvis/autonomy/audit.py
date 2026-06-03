"""Audit-report builder over the Persisted Event Log."""

from __future__ import annotations

from typing import Any, Dict, Optional


def build_audit_report(
    event_log_store: Any,
    *,
    since: Optional[float] = None,
    until: Optional[float] = None,
    agent_id: Optional[str] = None,
    task_id: Optional[str] = None,
    project_id: Optional[str] = None,
    limit: int = 500,
) -> Dict[str, Any]:
    """Compile an audit report of Event Log activity over a window.

    Returns ``{window, filters, events, count}`` (plus a ``note`` when the
    event-log store is not configured).
    """
    window = {"since": since, "until": until}
    filters = {
        "agent_id": agent_id,
        "task_id": task_id,
        "project_id": project_id,
    }
    if event_log_store is None:
        return {
            "window": window,
            "filters": filters,
            "events": [],
            "count": 0,
            "note": "event log not configured",
        }
    records = event_log_store.query(
        agent_id=agent_id,
        task_id=task_id,
        project_id=project_id,
        since=since,
        until=until,
        limit=limit,
    )
    events = [
        {
            "id": r.id,
            "event_type": r.event_type,
            "timestamp": r.timestamp,
            "agent_id": r.agent_id,
            "task_id": r.task_id,
            "project_id": r.project_id,
            "data": r.data,
        }
        for r in records
    ]
    return {
        "window": window,
        "filters": filters,
        "events": events,
        "count": len(events),
    }
