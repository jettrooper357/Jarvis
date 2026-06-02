from __future__ import annotations

from fastapi import FastAPI

from openjarvis.server.api_routes import include_all_routes


def test_action_approvals_routes_are_mounted():
    app = FastAPI()
    include_all_routes(app)
    paths = {route.path for route in app.routes}
    assert "/v1/action-approvals" in paths
    assert "/v1/action-approvals/{approval_id}/resolve" in paths
