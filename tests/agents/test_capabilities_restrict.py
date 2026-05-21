"""Tests for the restrict_to_tool_names filter on build_agent_tool_instances.

The chief's per-delegation tools_allowed is enforced here: an
``Optional[Iterable[str]]`` parameter that, when set, narrows the
returned toolset to a strict subset (least privilege).
"""

from __future__ import annotations

from openjarvis.agents.capabilities import build_agent_tool_instances


def _minimal_agent_record(agent_id: str = "leaf-1") -> dict:
    """Agent record with no skills, default agent_type, no org_role.

    With these defaults, ``effective_agent_tool_names`` adds the
    ``AUTO_COLLABORATION_TOOLS`` set automatically.
    """
    return {
        "id": agent_id,
        "name": "Leaf One",
        "agent_type": "monitor_operative",
        "org_role": "",
        "config": {},
    }


def test_no_restriction_returns_full_auto_set():
    tools = build_agent_tool_instances(
        _minimal_agent_record(),
        engine=None,
        model="fake-model",
    )
    names = {t.spec.name for t in tools}
    # AUTO_COLLABORATION_TOOLS should all be present
    assert "managed_agent_directory" in names
    assert "managed_agent_delegate" in names


def test_restrict_to_subset_narrows_toolset():
    tools = build_agent_tool_instances(
        _minimal_agent_record(),
        engine=None,
        model="fake-model",
        restrict_to_tool_names=["managed_agent_directory"],
    )
    names = [t.spec.name for t in tools]
    assert names == ["managed_agent_directory"]


def test_restrict_to_empty_set_returns_empty_list():
    """Empty set means 'no tools at all' -- a valid least-privilege policy."""
    tools = build_agent_tool_instances(
        _minimal_agent_record(),
        engine=None,
        model="fake-model",
        restrict_to_tool_names=[],
    )
    assert tools == []


def test_restrict_to_unknown_tool_returns_empty_list():
    """Names that aren't in the agent's effective set are silently dropped."""
    tools = build_agent_tool_instances(
        _minimal_agent_record(),
        engine=None,
        model="fake-model",
        restrict_to_tool_names=["definitely_not_a_real_tool"],
    )
    assert tools == []


def test_restrict_is_intersection_not_union():
    """tools_allowed can never broaden access beyond the agent's config."""
    tools_full = build_agent_tool_instances(
        _minimal_agent_record(),
        engine=None,
        model="fake-model",
    )
    full_names = {t.spec.name for t in tools_full}
    # Pick a name we know is in the effective set
    keep = next(iter(full_names))
    # Ask for that + a tool the agent doesn't have
    tools_restricted = build_agent_tool_instances(
        _minimal_agent_record(),
        engine=None,
        model="fake-model",
        restrict_to_tool_names=[keep, "definitely_not_a_real_tool"],
    )
    assert {t.spec.name for t in tools_restricted} == {keep}
