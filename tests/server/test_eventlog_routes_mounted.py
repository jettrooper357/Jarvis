from __future__ import annotations

from fastapi import FastAPI

from openjarvis.server.api_routes import include_all_routes


def test_eventlog_routes_are_mounted():
    app = FastAPI()
    include_all_routes(app)
    paths = {route.path for route in app.routes}
    assert "/v1/events" in paths
    assert "/v1/events/feed" in paths
