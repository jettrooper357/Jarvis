from openjarvis.agents._stubs import AgentResult
from openjarvis.agents.executor import AgentExecutor
from openjarvis.agents.manager import AgentManager
from openjarvis.core.events import EventBus, EventType


def test_budget_exceeded_sets_status(tmp_path):
    """Agent exceeding max_cost gets status budget_exceeded."""
    mgr = AgentManager(str(tmp_path / "test.db"))
    bus = EventBus(record_history=True)
    executor = AgentExecutor(mgr, bus)

    agent = mgr.create_agent("expensive", config={"max_cost": 1.0})
    mgr.start_tick(agent["id"])

    result = AgentResult(content="done", metadata={"cost": 1.50, "tokens_used": 100})
    executor._finalize_tick(agent["id"], result, error=None, duration=1.0)

    updated = mgr.get_agent(agent["id"])
    assert updated["status"] == "budget_exceeded"

    budget_events = [
        e for e in bus.history if e.event_type == EventType.AGENT_BUDGET_EXCEEDED
    ]
    assert len(budget_events) == 1
    mgr.close()


def test_budget_not_exceeded_stays_idle(tmp_path):
    """Agent under budget stays idle."""
    mgr = AgentManager(str(tmp_path / "test.db"))
    bus = EventBus(record_history=True)
    executor = AgentExecutor(mgr, bus)

    agent = mgr.create_agent("cheap", config={"max_cost": 10.0})
    mgr.start_tick(agent["id"])

    result = AgentResult(content="done", metadata={"cost": 0.50, "tokens_used": 50})
    executor._finalize_tick(agent["id"], result, error=None, duration=1.0)

    updated = mgr.get_agent(agent["id"])
    assert updated["status"] == "idle"
    mgr.close()


def test_budget_unlimited_skips_check(tmp_path):
    """max_cost=0 means unlimited — no budget enforcement."""
    mgr = AgentManager(str(tmp_path / "test.db"))
    bus = EventBus()
    executor = AgentExecutor(mgr, bus)

    agent = mgr.create_agent("unlimited", config={"max_cost": 0})
    mgr.start_tick(agent["id"])

    result = AgentResult(
        content="done",
        metadata={"cost": 999.99, "tokens_used": 1000000},
    )
    executor._finalize_tick(agent["id"], result, error=None, duration=1.0)

    updated = mgr.get_agent(agent["id"])
    assert updated["status"] == "idle"
    mgr.close()


def test_token_budget_exceeded(tmp_path):
    """Agent exceeding budget_max_tokens gets budget_exceeded."""
    mgr = AgentManager(str(tmp_path / "test.db"))
    bus = EventBus()
    executor = AgentExecutor(mgr, bus)

    agent = mgr.create_agent("token-heavy", config={"budget_max_tokens": 1000})
    mgr.start_tick(agent["id"])

    result = AgentResult(content="done", metadata={"cost": 0.01, "tokens_used": 1500})
    executor._finalize_tick(agent["id"], result, error=None, duration=1.0)

    updated = mgr.get_agent(agent["id"])
    assert updated["status"] == "budget_exceeded"
    mgr.close()


def test_generation_max_tokens_is_not_a_budget(tmp_path):
    """A per-completion max_tokens must NOT trip the lifetime token budget."""
    mgr = AgentManager(str(tmp_path / "test.db"))
    bus = EventBus()
    executor = AgentExecutor(mgr, bus)

    # 4096 is the classic generation output cap (e.g. monitor_operative default).
    agent = mgr.create_agent("chief-like", config={"max_tokens": 4096})
    mgr.start_tick(agent["id"])

    result = AgentResult(content="done", metadata={"tokens_used": 57565})
    executor._finalize_tick(agent["id"], result, error=None, duration=1.0)

    updated = mgr.get_agent(agent["id"])
    assert updated["status"] == "idle"
    mgr.close()


def test_config_update_to_unlimited_clears_budget_exceeded(tmp_path):
    """Setting budget to unlimited clears a stuck budget_exceeded status."""
    mgr = AgentManager(str(tmp_path / "test.db"))
    bus = EventBus()
    executor = AgentExecutor(mgr, bus)

    agent = mgr.create_agent("spendy", config={"max_cost": 1.0})
    mgr.start_tick(agent["id"])
    result = AgentResult(content="done", metadata={"cost": 5.0, "tokens_used": 100})
    executor._finalize_tick(agent["id"], result, error=None, duration=1.0)
    assert mgr.get_agent(agent["id"])["status"] == "budget_exceeded"

    # User removes the cap (Budget: Unlimited) — badge must clear. Preserve the
    # generation max_tokens so we also prove it is not treated as a budget.
    mgr.update_agent(agent["id"], config={"max_cost": 0, "max_tokens": 4096})
    assert mgr.get_agent(agent["id"])["status"] == "idle"
    mgr.close()


def test_config_update_raising_cap_clears_budget_exceeded(tmp_path):
    """Raising max_cost above accrued cost clears budget_exceeded."""
    mgr = AgentManager(str(tmp_path / "test.db"))
    bus = EventBus()
    executor = AgentExecutor(mgr, bus)

    agent = mgr.create_agent("spendy", config={"max_cost": 1.0})
    mgr.start_tick(agent["id"])
    result = AgentResult(content="done", metadata={"cost": 5.0, "tokens_used": 100})
    executor._finalize_tick(agent["id"], result, error=None, duration=1.0)
    assert mgr.get_agent(agent["id"])["status"] == "budget_exceeded"

    mgr.update_agent(agent["id"], config={"max_cost": 100.0})
    assert mgr.get_agent(agent["id"])["status"] == "idle"
    mgr.close()


def test_config_update_still_over_cap_stays_budget_exceeded(tmp_path):
    """If the new cap is still below accrued cost, status stays exceeded."""
    mgr = AgentManager(str(tmp_path / "test.db"))
    bus = EventBus()
    executor = AgentExecutor(mgr, bus)

    agent = mgr.create_agent("spendy", config={"max_cost": 1.0})
    mgr.start_tick(agent["id"])
    result = AgentResult(content="done", metadata={"cost": 5.0, "tokens_used": 100})
    executor._finalize_tick(agent["id"], result, error=None, duration=1.0)
    assert mgr.get_agent(agent["id"])["status"] == "budget_exceeded"

    # Raise the cap a little, but still under the 5.0 already spent.
    mgr.update_agent(agent["id"], config={"max_cost": 2.0})
    assert mgr.get_agent(agent["id"])["status"] == "budget_exceeded"
    mgr.close()


def test_config_update_does_not_disturb_non_budget_status(tmp_path):
    """A config edit on a normal agent must not flip its status to idle."""
    mgr = AgentManager(str(tmp_path / "test.db"))
    agent = mgr.create_agent("normal", config={"max_cost": 0})
    mgr.update_agent(agent["id"], status="running")

    mgr.update_agent(agent["id"], config={"max_cost": 0, "model": "qwen2.5"})
    assert mgr.get_agent(agent["id"])["status"] == "running"
    mgr.close()
