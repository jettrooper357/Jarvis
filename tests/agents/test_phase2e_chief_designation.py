"""Phase 2E commit 1 — AgentManager Chief designation tests.

Covers:
- migration adds the ``is_chief`` column without breaking legacy reads.
- ``get_chief_agent`` / ``set_chief_agent`` round-trip.
- ``set_chief_agent`` is atomic: any prior Chief is cleared.
- Back-fill auto-promotes the first matching role on a fresh install.
- Back-fill is a no-op when no role matches.
- ``clear_chief_designation`` drops the flag idempotently.
- Errors: missing agent, archived agent.
"""

from __future__ import annotations

from openjarvis.agents.manager import AgentManager


def test_legacy_agent_rows_read_with_is_chief_false(tmp_path) -> None:
    """A row inserted via the existing create_agent path defaults to non-chief."""
    mgr = AgentManager(str(tmp_path / "agents.db"))
    a = mgr.create_agent("plain")
    fetched = mgr.get_agent(a["id"])
    assert fetched is not None
    assert fetched["is_chief"] is False
    mgr.close()


def test_get_chief_returns_none_when_no_chief(tmp_path) -> None:
    mgr = AgentManager(str(tmp_path / "agents.db"))
    mgr.create_agent("plain", org_role="data analyst")
    assert mgr.get_chief_agent() is None
    mgr.close()


def test_set_chief_designates_the_agent(tmp_path) -> None:
    mgr = AgentManager(str(tmp_path / "agents.db"))
    a = mgr.create_agent("captain", org_role="operations lead")
    designated = mgr.set_chief_agent(a["id"])
    assert designated["is_chief"] is True
    chief = mgr.get_chief_agent()
    assert chief is not None
    assert chief["id"] == a["id"]
    mgr.close()


def test_set_chief_is_atomic_only_one_at_a_time(tmp_path) -> None:
    mgr = AgentManager(str(tmp_path / "agents.db"))
    a = mgr.create_agent("alpha")
    b = mgr.create_agent("bravo")
    mgr.set_chief_agent(a["id"])
    mgr.set_chief_agent(b["id"])
    # Only b carries the flag now.
    assert mgr.get_chief_agent()["id"] == b["id"]
    # Spot-check a directly: not chief any more.
    assert mgr.get_agent(a["id"])["is_chief"] is False
    mgr.close()


def test_set_chief_unknown_agent_raises(tmp_path) -> None:
    mgr = AgentManager(str(tmp_path / "agents.db"))
    try:
        mgr.set_chief_agent("nonexistent")
    except ValueError as exc:
        assert "not found" in str(exc).lower()
    else:  # pragma: no cover
        raise AssertionError("expected ValueError")
    mgr.close()


def test_set_chief_archived_agent_raises(tmp_path) -> None:
    mgr = AgentManager(str(tmp_path / "agents.db"))
    a = mgr.create_agent("dropped")
    mgr.delete_agent(a["id"])  # marks archived
    try:
        mgr.set_chief_agent(a["id"])
    except ValueError as exc:
        assert "archived" in str(exc).lower()
    else:  # pragma: no cover
        raise AssertionError("expected ValueError")
    mgr.close()


def test_clear_chief_designation_is_idempotent(tmp_path) -> None:
    mgr = AgentManager(str(tmp_path / "agents.db"))
    a = mgr.create_agent("transient")
    mgr.set_chief_agent(a["id"])
    assert mgr.get_chief_agent() is not None
    mgr.clear_chief_designation()
    assert mgr.get_chief_agent() is None
    # Second call is also a no-op.
    mgr.clear_chief_designation()
    assert mgr.get_chief_agent() is None
    mgr.close()


def test_backfill_auto_promotes_matching_role(tmp_path) -> None:
    """First boot with a matching org_role auto-marks that agent as Chief."""
    db_path = str(tmp_path / "agents.db")
    mgr = AgentManager(db_path)
    mgr.create_agent("nobody", org_role="data analyst")
    a = mgr.create_agent("the boss", org_role="Chief Orchestrator")
    mgr.create_agent("ceo-impostor", org_role="ceo")  # also matches but later
    # No agent is currently chief — back-fill ran on init but the
    # creates above happened AFTER the constructor. So re-construct to
    # trigger back-fill against the seeded rows.
    mgr.close()
    mgr2 = AgentManager(db_path)
    chief = mgr2.get_chief_agent()
    assert chief is not None
    # The first matching row (by SELECT order) gets promoted.
    assert chief["id"] in (a["id"],)  # the explicit match
    mgr2.close()


def test_backfill_noop_when_no_role_matches(tmp_path) -> None:
    db_path = str(tmp_path / "agents.db")
    mgr = AgentManager(db_path)
    mgr.create_agent("worker-1", org_role="data analyst")
    mgr.create_agent("worker-2", org_role="qa engineer")
    mgr.close()
    mgr2 = AgentManager(db_path)
    assert mgr2.get_chief_agent() is None
    mgr2.close()


def test_backfill_noop_when_chief_already_set(tmp_path) -> None:
    """Re-initialising must not re-promote if a Chief is already designated."""
    db_path = str(tmp_path / "agents.db")
    mgr = AgentManager(db_path)
    a = mgr.create_agent("manual-pick", org_role="ops lead")
    b = mgr.create_agent("would-auto-promote", org_role="Chief Orchestrator")
    mgr.set_chief_agent(a["id"])
    mgr.close()
    mgr2 = AgentManager(db_path)
    chief = mgr2.get_chief_agent()
    # The manual designation survives; back-fill does NOT overwrite it.
    assert chief["id"] == a["id"]
    assert mgr2.get_agent(b["id"])["is_chief"] is False
    mgr2.close()
