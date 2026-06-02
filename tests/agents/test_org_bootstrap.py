from __future__ import annotations

from openjarvis.agents.manager import AgentManager
from openjarvis.agents.org import (
    DEFAULT_ORG,
    bootstrap_default_org,
    build_org_tree,
)


def _mgr(tmp_path):
    return AgentManager(db_path=str(tmp_path / "agents.db"))


def test_bootstrap_creates_full_tree(tmp_path):
    mgr = _mgr(tmp_path)
    summary = bootstrap_default_org(mgr)
    assert len(summary["created"]) == len(DEFAULT_ORG)
    assert summary["skipped"] == []
    agents = mgr.list_agents()
    assert len(agents) == len(DEFAULT_ORG)
    chiefs = [a for a in agents if a.get("is_chief")]
    assert len(chiefs) == 1
    assert summary["chief_id"] == chiefs[0]["id"]
    by_role = {a["org_role"]: a for a in agents}
    chief_id = chiefs[0]["id"]
    assert by_role["executive_assistant"]["manager_agent_id"] == chief_id
    assert by_role["cto_architect"]["manager_agent_id"] == chief_id
    assert (
        by_role["code_developer"]["manager_agent_id"]
        == by_role["cto_architect"]["id"]
    )


def test_bootstrap_is_idempotent(tmp_path):
    mgr = _mgr(tmp_path)
    bootstrap_default_org(mgr)
    second = bootstrap_default_org(mgr)
    assert second["created"] == []
    assert len(second["skipped"]) == len(DEFAULT_ORG)
    assert len(mgr.list_agents()) == len(DEFAULT_ORG)


def test_bootstrap_fills_only_missing(tmp_path):
    mgr = _mgr(tmp_path)
    mgr.create_from_template(
        "chief_orchestrator", name="Existing Chief", org_role="chief_orchestrator"
    )
    summary = bootstrap_default_org(mgr)
    assert "chief_orchestrator" in summary["skipped"]
    assert len(summary["created"]) == len(DEFAULT_ORG) - 1
    assert len(mgr.list_agents()) == len(DEFAULT_ORG)


def test_build_org_tree_nests_under_chief(tmp_path):
    mgr = _mgr(tmp_path)
    bootstrap_default_org(mgr)
    tree = build_org_tree(mgr)
    assert tree is not None
    assert tree["org_role"] == "chief_orchestrator"
    assert len(tree["reports"]) == 5
    cto = next(c for c in tree["reports"] if c["org_role"] == "cto_architect")
    assert len(cto["reports"]) == 5


def test_build_org_tree_none_when_no_chief(tmp_path):
    mgr = _mgr(tmp_path)
    assert build_org_tree(mgr) is None
