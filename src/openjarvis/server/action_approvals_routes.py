"""Read/write REST routes for the generalized Approval Center."""

from __future__ import annotations

import datetime
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from openjarvis.approvals_center.store import (
    ActionApproval,
    ActionApprovalError,
)

action_approvals_router = APIRouter(
    prefix="/v1/action-approvals", tags=["action-approvals"]
)


class CreateApprovalRequest(BaseModel):
    action_type: str
    summary: str
    payload: Dict[str, Any] = {}
    agent_id: str = ""
    task_id: str = ""
    project_id: str = ""
    requested_by: str = ""


class ResolveRequest(BaseModel):
    action: str
    resolved_by: Optional[str] = None
    reason: Optional[str] = None
    remind_at: Optional[float] = None
    followup_question: Optional[str] = None
    new_payload: Optional[Dict[str, Any]] = None


_VALID_ACTIONS = {"approve", "reject", "defer", "ask", "modify", "reopen"}


def _iso(ts: Optional[float]) -> Optional[str]:
    if not ts:
        return None
    return datetime.datetime.fromtimestamp(ts, tz=datetime.timezone.utc).isoformat()


def _serialise(a: ActionApproval) -> Dict[str, Any]:
    d = a.to_dict()
    d["created_at"] = _iso(a.requested_at)
    d["resolved_at_iso"] = _iso(a.resolved_at)
    return d


def _store_or_none(request: Request) -> Any:
    return getattr(request.app.state, "action_approval_store", None)


def _require_store(request: Request) -> Any:
    store = _store_or_none(request)
    if store is None:
        raise HTTPException(
            status_code=503,
            detail="Action approval store not configured on this server.",
        )
    return store


@action_approvals_router.get("")
async def list_approvals(
    request: Request,
    action_type: Optional[str] = None,
    state: Optional[str] = None,
    agent_id: Optional[str] = None,
    project_id: Optional[str] = None,
    limit: int = 100,
):
    store = _store_or_none(request)
    if store is None:
        return {"approvals": []}
    items = store.list(
        action_type=action_type,
        state=state,
        agent_id=agent_id,
        project_id=project_id,
        limit=limit,
    )
    return {"approvals": [_serialise(a) for a in items]}


@action_approvals_router.post("")
async def create_approval(request: Request, body: CreateApprovalRequest):
    store = _require_store(request)
    try:
        approval = store.request(
            action_type=body.action_type,
            summary=body.summary,
            payload=body.payload,
            agent_id=body.agent_id,
            task_id=body.task_id,
            project_id=body.project_id,
            requested_by=body.requested_by,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _serialise(approval)


@action_approvals_router.get("/{approval_id}")
async def get_approval(approval_id: str, request: Request):
    store = _store_or_none(request)
    if store is None:
        raise HTTPException(status_code=404, detail="Approval not found")
    approval = store.get(approval_id)
    if approval is None:
        raise HTTPException(status_code=404, detail="Approval not found")
    return _serialise(approval)


@action_approvals_router.get("/{approval_id}/history")
async def get_history(approval_id: str, request: Request):
    store = _store_or_none(request)
    if store is None:
        return {"history": []}
    return {"history": store.history(approval_id)}


@action_approvals_router.post("/{approval_id}/resolve")
async def resolve_approval(approval_id: str, request: Request, body: ResolveRequest):
    store = _require_store(request)
    if body.action not in _VALID_ACTIONS:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown action {body.action!r}; expected one of "
            f"{sorted(_VALID_ACTIONS)}.",
        )
    try:
        if body.action == "approve":
            result = store.approve(
                approval_id, resolved_by=body.resolved_by, reason=body.reason
            )
        elif body.action == "reject":
            result = store.reject(
                approval_id, resolved_by=body.resolved_by, reason=body.reason
            )
        elif body.action == "defer":
            result = store.defer(
                approval_id,
                remind_at=body.remind_at,
                resolved_by=body.resolved_by,
                reason=body.reason,
            )
        elif body.action == "ask":
            if not (body.followup_question or "").strip():
                raise HTTPException(
                    status_code=422,
                    detail="ask requires a followup_question.",
                )
            result = store.ask(
                approval_id,
                question=body.followup_question,
                resolved_by=body.resolved_by,
            )
        elif body.action == "modify":
            if body.new_payload is None:
                raise HTTPException(
                    status_code=422, detail="modify requires new_payload."
                )
            result = store.modify(
                approval_id,
                new_payload=body.new_payload,
                resolved_by=body.resolved_by,
                reason=body.reason,
            )
        else:  # reopen
            result = store.reopen(
                approval_id, resolved_by=body.resolved_by, reason=body.reason
            )
    except ActionApprovalError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _serialise(result)
