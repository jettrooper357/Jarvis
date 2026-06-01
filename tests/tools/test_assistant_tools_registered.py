from __future__ import annotations

import importlib

from openjarvis.core.registry import ToolRegistry


def test_assistant_tools_register_on_import():
    # conftest clears ToolRegistry each test; re-import the modules to
    # re-trigger their @ToolRegistry.register decorators.
    for mod in ("followup_tools", "decision_tools"):
        m = importlib.import_module(f"openjarvis.tools.{mod}")
        importlib.reload(m)
    for name in (
        "followup_add",
        "followup_list",
        "followup_resolve",
        "followup_sweep_stale",
        "decision_record",
        "decision_list",
    ):
        assert ToolRegistry.contains(name), name
