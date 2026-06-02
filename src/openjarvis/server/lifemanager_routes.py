"""Read/write REST routes for the Life Manager (domains + routines)."""

from __future__ import annotations

import datetime
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from openjarvis.lifemanager.store import LifeError

lifemanager_router = APIRouter(prefix="/v1/life", tags=["lifemanager"])


class CreateDomainRequest(BaseModel):
    name: str
    slug: str = ""
    description: str = ""


class CreateRoutineRequest(BaseModel):
    title: str
    domain_id: str = ""
    cadence: str = "daily"
    interval_days: int = 1


def _iso(ts: Optional[float]) -> Optional[str]:
    if not ts:
        return None
    return datetime.datetime.fromtimestamp(ts, tz=datetime.timezone.utc).isoformat()


def _domain_dict(d: Any) -> Dict[str, Any]:
    out = d.to_dict()
    out["created_at_iso"] = _iso(d.created_at)
    return out


def _routine_dict(r: Any) -> Dict[str, Any]:
    out = r.to_dict()
    out["next_due_at_iso"] = _iso(r.next_due_at)
    out["last_done_at_iso"] = _iso(r.last_done_at)
    return out


def _store_or_none(request: Request) -> Any:
    return getattr(request.app.state, "life_store", None)


def _require_store(request: Request) -> Any:
    store = _store_or_none(request)
    if store is None:
        raise HTTPException(
            status_code=503,
            detail="Life store not configured on this server.",
        )
    return store


@lifemanager_router.get("/domains")
async def list_domains(request: Request):
    store = _store_or_none(request)
    if store is None:
        return {"domains": []}
    return {"domains": [_domain_dict(d) for d in store.list_domains()]}


@lifemanager_router.post("/domains")
async def create_domain(request: Request, body: CreateDomainRequest):
    store = _require_store(request)
    try:
        d = store.add_domain(
            name=body.name, slug=body.slug, description=body.description
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _domain_dict(d)


@lifemanager_router.get("/routines")
async def list_routines(
    request: Request,
    domain_id: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 100,
):
    store = _store_or_none(request)
    if store is None:
        return {"routines": []}
    routines = store.list_routines(domain_id=domain_id, status=status, limit=limit)
    return {"routines": [_routine_dict(r) for r in routines]}


@lifemanager_router.post("/routines")
async def create_routine(request: Request, body: CreateRoutineRequest):
    store = _require_store(request)
    try:
        r = store.add_routine(
            title=body.title,
            domain_id=body.domain_id,
            cadence=body.cadence,
            interval_days=body.interval_days,
        )
    except (ValueError, LifeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _routine_dict(r)


@lifemanager_router.post("/routines/{routine_id}/complete")
async def complete_routine(routine_id: str, request: Request):
    store = _require_store(request)
    try:
        r = store.complete_routine(routine_id)
    except LifeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _routine_dict(r)


@lifemanager_router.get("/due")
async def due(request: Request, limit: int = 100, now: Optional[float] = None):
    store = _store_or_none(request)
    if store is None:
        return {"routines": []}
    routines = store.due(now=now, limit=limit)
    return {"routines": [_routine_dict(r) for r in routines]}
