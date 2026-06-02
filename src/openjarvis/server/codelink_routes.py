"""Read-only REST routes for Task–Code Linkage."""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Request

codelink_router = APIRouter(prefix="/v1/codelink", tags=["codelink"])


def _store(request: Request) -> Any:
    return getattr(request.app.state, "codelink_store", None)


@codelink_router.get("/file-events")
async def list_file_events(
    request: Request,
    path: Optional[str] = None,
    project_id: Optional[str] = None,
    task_id: Optional[str] = None,
    limit: int = 100,
):
    store = _store(request)
    if store is None:
        return {"file_events": []}
    events = store.file_events(
        path=path, project_id=project_id, task_id=task_id, limit=limit
    )
    return {"file_events": [e.to_dict() for e in events]}


@codelink_router.get("/commits")
async def list_commits(
    request: Request,
    commit_sha: Optional[str] = None,
    task_id: Optional[str] = None,
    project_id: Optional[str] = None,
    limit: int = 100,
):
    store = _store(request)
    if store is None:
        return {"commits": []}
    commits = store.commits(
        commit_sha=commit_sha, task_id=task_id, project_id=project_id, limit=limit
    )
    return {"commits": [c.to_dict() for c in commits]}


@codelink_router.get("/tasks/{task_id}")
async def task_view(task_id: str, request: Request):
    store = _store(request)
    if store is None:
        return {"file_events": [], "commits": []}
    combined = store.events_for_task(task_id)
    return {
        "file_events": [e.to_dict() for e in combined["file_events"]],
        "commits": [c.to_dict() for c in combined["commits"]],
    }


@codelink_router.get("/status")
async def status(request: Request):
    from openjarvis.codelink.watcher import watchdog_available

    mgr = getattr(request.app.state, "codelink_watchers", None)
    active = mgr.active if mgr is not None else 0
    return {
        "watchdog_available": watchdog_available(),
        "store_configured": _store(request) is not None,
        "active_watchers": active,
    }
