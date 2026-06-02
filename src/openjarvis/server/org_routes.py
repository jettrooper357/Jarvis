"""REST routes for the agent org: bootstrap + hierarchy tree."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request

org_router = APIRouter(prefix="/v1/org", tags=["org"])


def _manager(request: Request) -> Any:
    return getattr(request.app.state, "agent_manager", None)


@org_router.get("")
async def get_org(request: Request):
    manager = _manager(request)
    if manager is None:
        return {"org": None}
    from openjarvis.agents.org import build_org_tree

    return {"org": build_org_tree(manager)}


@org_router.post("/bootstrap")
async def bootstrap(request: Request):
    manager = _manager(request)
    if manager is None:
        raise HTTPException(
            status_code=503,
            detail="Agent manager not configured on this server.",
        )
    from openjarvis.agents.org import bootstrap_default_org

    return bootstrap_default_org(manager)
