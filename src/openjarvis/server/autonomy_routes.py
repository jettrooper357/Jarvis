"""REST routes for Controlled Autonomy: rollback + audit report."""

from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from openjarvis.autonomy.rollback_store import RollbackError

autonomy_router = APIRouter(prefix="/v1", tags=["autonomy"])


class RecordRequest(BaseModel):
    action_type: str
    summary: str
    undo_payload: Dict[str, Any] = {}
    agent_id: str = ""
    task_id: str = ""
    reversible: bool = True


class RevertRequest(BaseModel):
    note: str = ""


def _rollback(request: Request) -> Any:
    return getattr(request.app.state, "rollback_store", None)


def _eventlog(request: Request) -> Any:
    return getattr(request.app.state, "event_log_store", None)


@autonomy_router.get("/rollback")
async def list_actions(
    request: Request,
    status: Optional[str] = None,
    agent_id: Optional[str] = None,
    action_type: Optional[str] = None,
    limit: int = 100,
):
    store = _rollback(request)
    if store is None:
        return {"actions": []}
    items = store.list(
        status=status, agent_id=agent_id, action_type=action_type, limit=limit
    )
    return {"actions": [a.to_dict() for a in items]}


@autonomy_router.post("/rollback")
async def record_action(request: Request, body: RecordRequest):
    store = _rollback(request)
    if store is None:
        raise HTTPException(status_code=503, detail="Rollback store not configured.")
    try:
        a = store.record(
            action_type=body.action_type,
            summary=body.summary,
            undo_payload=body.undo_payload,
            agent_id=body.agent_id,
            task_id=body.task_id,
            reversible=body.reversible,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return a.to_dict()


@autonomy_router.get("/rollback/{action_id}")
async def get_action(action_id: str, request: Request):
    store = _rollback(request)
    if store is None:
        raise HTTPException(status_code=404, detail="Action not found")
    a = store.get(action_id)
    if a is None:
        raise HTTPException(status_code=404, detail="Action not found")
    return a.to_dict()


@autonomy_router.post("/rollback/{action_id}/revert")
async def revert_action(action_id: str, request: Request, body: RevertRequest):
    store = _rollback(request)
    if store is None:
        raise HTTPException(status_code=503, detail="Rollback store not configured.")
    try:
        a = store.revert(action_id, note=body.note)
    except RollbackError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return a.to_dict()


@autonomy_router.get("/audit/report")
async def audit_report(
    request: Request,
    since: Optional[float] = None,
    until: Optional[float] = None,
    agent_id: Optional[str] = None,
    task_id: Optional[str] = None,
    project_id: Optional[str] = None,
    limit: int = 500,
):
    from openjarvis.autonomy.audit import build_audit_report

    return build_audit_report(
        _eventlog(request),
        since=since,
        until=until,
        agent_id=agent_id,
        task_id=task_id,
        project_id=project_id,
        limit=limit,
    )
