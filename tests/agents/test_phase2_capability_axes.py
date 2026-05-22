"""Phase 2A — capability axis resolution tests.

Locks in the 6-axis output of ``resolve_capability_axes`` and the new
keys added to ``enrich_agent_record``. Existing keys (configured_*,
effective_*, auto_tools, knowledge_enabled, template_id) keep their
current semantics — those are guarded by the contract snapshot test
below.
"""

from __future__ import annotations

from openjarvis.agents.capabilities import (
    enrich_agent_record,
    resolve_capability_axes,
)


def _agent(config=None, **rest):
    rec = {
        "id": "agt-1",
        "name": "Worker",
        "agent_type": "monitor_operative",
        "org_role": "",
        "config": config or {},
    }
    rec.update(rest)
    return rec


def test_axes_empty_when_no_policy_no_manager() -> None:
    axes = resolve_capability_axes(_agent())
    assert axes["assigned_skills"] == []
    assert axes["assigned_tools"] == []
    assert axes["inherited_skills"] == []
    assert axes["inherited_tools"] == []
    assert axes["blocked_skills"] == []
    assert axes["blocked_tools"] == []
    assert axes["requires_approval_skills"] == []
    assert axes["requires_approval_tools"] == []
    # Effective always non-None; tools include auto-injected collab tools.
    assert "managed_agent_delegate" in axes["effective_tools"]
    assert axes["effective_skills"] == []


def test_assigned_appears_in_axes_and_effective() -> None:
    agent = _agent(config={"skills": ["data_viz", "sql"], "tools": ["browser"]})
    axes = resolve_capability_axes(agent)
    assert axes["assigned_skills"] == ["data_viz", "sql"]
    assert "browser" in axes["assigned_tools"]
    assert "browser" in axes["effective_tools"]
    assert set(axes["effective_skills"]) == {"data_viz", "sql"}


def test_blocked_removes_from_effective_even_when_inherited() -> None:
    manager = _agent(config={"skills": ["confidential", "ok"]})
    agent = _agent(
        config={
            "skills": ["ok"],
            "blocked_skills": ["confidential"],
        }
    )
    axes = resolve_capability_axes(agent, manager_record=manager)
    # Inherited from manager minus already-assigned.
    assert axes["inherited_skills"] == ["confidential"]
    # Blocked wins: 'confidential' must not appear in effective.
    assert "confidential" not in axes["effective_skills"]
    assert "ok" in axes["effective_skills"]


def test_inherited_excludes_locally_assigned() -> None:
    manager = _agent(config={"skills": ["alpha", "beta"]})
    agent = _agent(config={"skills": ["alpha"]})
    axes = resolve_capability_axes(agent, manager_record=manager)
    # 'alpha' is assigned locally, so it's NOT listed as inherited.
    assert axes["inherited_skills"] == ["beta"]
    # But it IS in effective.
    assert "alpha" in axes["effective_skills"]
    assert "beta" in axes["effective_skills"]


def test_requires_approval_lists_are_returned_verbatim() -> None:
    agent = _agent(
        config={
            "requires_approval_skills": ["wire_money"],
            "requires_approval_tools": ["delete_files"],
        }
    )
    axes = resolve_capability_axes(agent)
    assert axes["requires_approval_skills"] == ["wire_money"]
    assert axes["requires_approval_tools"] == ["delete_files"]


def test_enrich_agent_record_returns_new_axis_keys() -> None:
    enriched = enrich_agent_record(_agent(config={"skills": ["s1"]}))
    # All six new axis keys present, lists not None.
    for key in (
        "inherited_skills",
        "inherited_tools",
        "blocked_skills",
        "blocked_tools",
        "requires_approval_skills",
        "requires_approval_tools",
    ):
        assert key in enriched
        assert isinstance(enriched[key], list)


def test_enrich_agent_record_existing_keys_preserve_semantics() -> None:
    """Contract snapshot: pre-2A keys keep their meaning."""
    # ``knowledge_enabled: False`` makes the test hermetic regardless of
    # whether the local user has a populated ``~/.openjarvis/knowledge.db``.
    enriched = enrich_agent_record(
        _agent(
            config={
                "skills": ["sk"],
                "tools": ["browser"],
                "knowledge_enabled": False,
            }
        )
    )
    # configured_* echo the config; effective_skills aliases configured_skills.
    assert enriched["configured_skills"] == ["sk"]
    assert enriched["configured_tools"] == ["browser"]
    assert enriched["effective_skills"] == ["sk"]
    # auto_tools are everything in effective_tools that wasn't configured.
    assert "browser" not in enriched["auto_tools"]
    assert "managed_agent_delegate" in enriched["auto_tools"]
    # template_id falls back to empty string.
    assert enriched["template_id"] == ""
    # knowledge_enabled is False because the config explicitly disables it.
    assert enriched["knowledge_enabled"] is False


def test_enrich_with_manager_populates_inherited() -> None:
    manager = _agent(config={"skills": ["analytics"]})
    enriched = enrich_agent_record(_agent(config={"skills": ["ui"]}), manager)
    assert enriched["inherited_skills"] == ["analytics"]
