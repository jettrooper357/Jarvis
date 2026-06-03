from __future__ import annotations

from fastapi import FastAPI

from openjarvis.server.api_routes import include_all_routes


def test_autonomy_routes_are_mounted():
    app = FastAPI()
    include_all_routes(app)
    paths = {route.path for route in app.routes}
    assert "/v1/rollback" in paths
    assert "/v1/rollback/{action_id}/revert" in paths
    assert "/v1/audit/report" in paths
