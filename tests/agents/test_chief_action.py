"""Doc-scenario tests for OrchestratorAgent in chief mode.

These mirror the three concrete scenarios in the Chief Orchestrator
design doc: a simple direct request, a multi-step delegated request
with aggregation, and a failure with escalation. They use a scripted
fake engine and an injected delegate_fn so the tests are deterministic.
"""

from __future__ import annotations

import json
from typing import Callable, List

import pytest

from openjarvis.agents.chief import (
    ActionType,
    OrchestratorAction,
    ParseError,
    parse_action,
)
from openjarvis.agents.orchestrator import OrchestratorAgent
from tests.agents.fake_engine import FakeEngine


# ---------------------------------------------------------------------------
# Parser unit tests
# ---------------------------------------------------------------------------


def test_parse_action_complete_minimal():
    payload = json.dumps(
        {
            "action": "complete",
            "reason": "trivial lookup",
            "final_report": {
                "status": "completed",
                "summary": "Run run_9f2a succeeded.",
            },
        }
    )
    action = parse_action(payload)
    assert action.action is ActionType.COMPLETE
    assert action.final_report is not None
    assert action.final_report.status == "completed"
    assert action.final_report.summary == "Run run_9f2a succeeded."


def test_parse_action_extracts_fenced_json():
    text = (
        "Here is my action:\n"
        "```json\n"
        '{"action":"fail","reason":"policy denied"}\n'
        "```\n"
    )
    action = parse_action(text)
    assert action.action is ActionType.FAIL
    assert action.reason == "policy denied"


def test_parse_action_rejects_complete_without_report():
    with pytest.raises(ParseError, match="final_report"):
        parse_action(json.dumps({"action": "complete", "reason": "no report"}))


def test_parse_action_rejects_delegate_without_delegations():
    with pytest.raises(ParseError, match="delegation"):
        parse_action(json.dumps({"action": "delegate", "reason": "x"}))


def test_parse_action_execute_direct_requires_tool_calls():
    """execute_direct is now a real action, not an alias for complete."""
    bad = json.dumps({"action": "execute_direct", "reason": "no calls"})
    with pytest.raises(ParseError, match="execute_direct"):
        parse_action(bad)

    good = json.dumps(
        {
            "action": "execute_direct",
            "reason": "one call",
            "tool_calls": [
                {"name": "project_create", "arguments": {"name": "Jarvis"}}
            ],
        }
    )
    action = parse_action(good)
    assert action.action is ActionType.EXECUTE_DIRECT
    assert len(action.tool_calls) == 1
    assert action.tool_calls[0].name == "project_create"
    # dict arguments get JSON-stringified for the executor
    assert "Jarvis" in action.tool_calls[0].arguments


def test_parse_action_execute_direct_accepts_string_arguments():
    """The chief may emit pre-serialized JSON in arguments; preserve it."""
    payload = json.dumps(
        {
            "action": "execute_direct",
            "reason": "string args",
            "tool_calls": [
                {"name": "project_create", "arguments": '{"name":"Jarvis"}'}
            ],
        }
    )
    action = parse_action(payload)
    assert action.tool_calls[0].arguments == '{"name":"Jarvis"}'


def test_parse_delegation_tools_allowed_list_preserved():
    payload = json.dumps(
        {
            "action": "delegate",
            "reason": "scoped",
            "delegations": [
                {
                    "agent_name_or_id": "leaf",
                    "message": "do X",
                    "tools_allowed": ["web_search", "calculator"],
                }
            ],
        }
    )
    action = parse_action(payload)
    assert action.delegations[0].tools_allowed == ["web_search", "calculator"]


def test_parse_delegation_tools_allowed_empty_list_preserved():
    """An empty list is meaningful ('no tools at all') -- not None."""
    payload = json.dumps(
        {
            "action": "delegate",
            "reason": "scoped",
            "delegations": [
                {
                    "agent_name_or_id": "leaf",
                    "message": "do X from prompt alone",
                    "tools_allowed": [],
                }
            ],
        }
    )
    action = parse_action(payload)
    assert action.delegations[0].tools_allowed == []


def test_parse_delegation_tools_allowed_omitted_is_none():
    payload = json.dumps(
        {
            "action": "delegate",
            "reason": "default",
            "delegations": [
                {"agent_name_or_id": "leaf", "message": "do X"}
            ],
        }
    )
    action = parse_action(payload)
    assert action.delegations[0].tools_allowed is None


def test_parse_delegation_tools_allowed_rejects_non_list():
    payload = json.dumps(
        {
            "action": "delegate",
            "reason": "bad",
            "delegations": [
                {
                    "agent_name_or_id": "leaf",
                    "message": "do X",
                    "tools_allowed": "calculator",
                }
            ],
        }
    )
    with pytest.raises(ParseError, match="tools_allowed"):
        parse_action(payload)


# ---------------------------------------------------------------------------
# Scenario harness
# ---------------------------------------------------------------------------


def _chief(
    responses: List[dict],
    *,
    delegate_fn: Callable[[str, str], str] | None = None,
) -> tuple[OrchestratorAgent, FakeEngine, list]:
    engine = FakeEngine(responses)
    delegations_seen: list = []

    if delegate_fn is not None:
        def _wrapped(agent_id: str, message: str, *, tools_allowed=None) -> str:
            delegations_seen.append((agent_id, message))
            try:
                return delegate_fn(  # type: ignore[call-arg]
                    agent_id, message, tools_allowed=tools_allowed
                )
            except TypeError:
                return delegate_fn(agent_id, message)
    else:
        _wrapped = None  # type: ignore[assignment]

    agent = OrchestratorAgent(
        engine=engine,
        model="fake-model",
        mode="chief",
        max_turns=4,
        delegate_fn=_wrapped,
        chief_registry={
            "worker.research.a": {"name": "Worker A", "role": "research"},
            "worker.research.b": {"name": "Worker B", "role": "research"},
            "worker.research.c": {"name": "Worker C", "role": "research"},
            "worker.ops.notifications": {"name": "Ops", "role": "ops"},
            "worker.ops.checklist": {"name": "Checker", "role": "ops"},
        },
    )
    return agent, engine, delegations_seen


# ---------------------------------------------------------------------------
# Scenario 1 — simple direct
# ---------------------------------------------------------------------------


def test_scenario_simple_direct():
    """Single complete action; no delegations; one model call."""
    response = {
        "content": json.dumps(
            {
                "action": "complete",
                "reason": "Direct read of run metadata is sufficient.",
                "final_report": {
                    "status": "completed",
                    "summary": (
                        "Run run_9f2a succeeded. Two child tasks completed, "
                        "one patch artifact was produced."
                    ),
                    "artifacts": ["artifact_patch_31"],
                },
            }
        ),
    }
    agent, engine, delegations = _chief([response])

    result = agent.run("Summarize the last run status.")

    assert engine.call_count == 1
    assert delegations == []
    assert result.turns == 1
    assert "run_9f2a succeeded" in result.content
    assert result.metadata["chief"]["action"] == "complete"
    assert result.metadata["chief"]["status"] == "completed"
    assert result.metadata["chief"]["artifacts"] == ["artifact_patch_31"]


# ---------------------------------------------------------------------------
# Scenario 2 — multi-step delegated with aggregation
# ---------------------------------------------------------------------------


_CHILD_ANALYSES = {
    "worker.research.a": "Backend A: strong traces, weak alerting. Score 7/10.",
    "worker.research.b": "Backend B: good metrics, self-host friendly. Score 8/10.",
    "worker.research.c": "Backend C: best alerting, expensive at scale. Score 6/10.",
}


def test_scenario_multi_step_delegated():
    """Delegate to three workers, then aggregate into one final report."""
    delegate_response = {
        "content": json.dumps(
            {
                "action": "delegate",
                "reason": "Three independent specialist evaluations.",
                "delegations": [
                    {
                        "agent_name_or_id": agent_id,
                        "message": f"Evaluate {agent_id.split('.')[-1].upper()}",
                        "acceptance_criteria": [
                            "Provide strengths and weaknesses",
                            "Return a recommendation score from 1-10",
                        ],
                        "budget_max_turns": 6,
                    }
                    for agent_id in (
                        "worker.research.a",
                        "worker.research.b",
                        "worker.research.c",
                    )
                ],
            }
        ),
    }
    complete_response = {
        "content": json.dumps(
            {
                "action": "complete",
                "reason": "All three evaluations returned; synthesizing.",
                "final_report": {
                    "status": "completed",
                    "summary": (
                        "Recommendation: Backend B. "
                        f"{_CHILD_ANALYSES['worker.research.a']} "
                        f"{_CHILD_ANALYSES['worker.research.b']} "
                        f"{_CHILD_ANALYSES['worker.research.c']}"
                    ),
                    "evidence": [
                        "worker.research.a",
                        "worker.research.b",
                        "worker.research.c",
                    ],
                },
            }
        ),
    }

    def fake_delegate(agent_id: str, _message: str) -> str:
        return _CHILD_ANALYSES[agent_id]

    agent, engine, delegations = _chief(
        [delegate_response, complete_response],
        delegate_fn=fake_delegate,
    )

    result = agent.run("Compare three candidate observability backends.")

    assert engine.call_count == 2
    assert len(delegations) == 3
    delegated_ids = [agent_id for agent_id, _ in delegations]
    assert delegated_ids == [
        "worker.research.a",
        "worker.research.b",
        "worker.research.c",
    ]
    # Acceptance criteria should be visible to the child
    assert "recommendation score" in delegations[0][1].lower()

    assert result.metadata["chief"]["action"] == "complete"
    assert result.metadata["chief"]["status"] == "completed"
    assert "Backend B" in result.content
    # All three analyses should appear in the final report
    for snippet in _CHILD_ANALYSES.values():
        assert snippet in result.content
    assert set(result.metadata["chief"]["evidence"]) == set(_CHILD_ANALYSES)


def test_scenario_multi_step_feeds_results_back_to_model():
    """The aggregation turn's prompt must include delegation results."""
    delegate_response = {
        "content": json.dumps(
            {
                "action": "delegate",
                "reason": "Need one specialist view.",
                "delegations": [
                    {
                        "agent_name_or_id": "worker.research.a",
                        "message": "Evaluate Backend A.",
                    }
                ],
            }
        ),
    }
    complete_response = {
        "content": json.dumps(
            {
                "action": "complete",
                "reason": "synthesized",
                "final_report": {"status": "completed", "summary": "ok"},
            }
        ),
    }

    captured_second_turn: list = []

    def fake_delegate(_agent_id: str, _message: str) -> str:
        return "Backend A: solid; score 7/10."

    agent, engine, _ = _chief(
        [delegate_response, complete_response],
        delegate_fn=fake_delegate,
    )
    # Intercept second engine call to inspect the messages
    original_generate = engine.generate

    def _spy_generate(messages, **kw):
        if engine.call_count == 1:
            captured_second_turn.append(list(messages))
        return original_generate(messages, **kw)

    engine.generate = _spy_generate  # type: ignore[method-assign]

    agent.run("Compare backends.")

    assert captured_second_turn, "second-turn messages were never captured"
    second_turn_text = "\n".join(
        getattr(m, "content", "") for m in captured_second_turn[0]
    )
    assert "Delegation results" in second_turn_text
    assert "Backend A: solid" in second_turn_text


# ---------------------------------------------------------------------------
# Scenario 3 — failure with partial result
# ---------------------------------------------------------------------------


def test_scenario_failure_with_partial_result():
    """One delegation succeeds, one fails; final_report is partial."""
    delegate_response = {
        "content": json.dumps(
            {
                "action": "delegate",
                "reason": "Validate then notify.",
                "delegations": [
                    {
                        "agent_name_or_id": "worker.ops.checklist",
                        "message": "Run the production deployment checklist.",
                    },
                    {
                        "agent_name_or_id": "worker.ops.notifications",
                        "message": "Post the status to Slack.",
                    },
                ],
            }
        ),
    }
    partial_response = {
        "content": json.dumps(
            {
                "action": "complete",
                "reason": (
                    "Checklist passed but Slack notification timed out twice."
                ),
                "final_report": {
                    "status": "partial",
                    "summary": (
                        "The deployment checklist completed. The Slack "
                        "notification did not. No hidden side effects were "
                        "executed without approval."
                    ),
                    "followups_needed": [
                        "Approve a background retry of the Slack notification "
                        "or send it manually."
                    ],
                },
            }
        ),
    }

    def fake_delegate(agent_id: str, _message: str) -> str:
        if agent_id == "worker.ops.notifications":
            raise TimeoutError("Slack API timeout after 2 retries")
        return "Checklist passed."

    agent, engine, delegations = _chief(
        [delegate_response, partial_response],
        delegate_fn=fake_delegate,
    )

    result = agent.run("Run prod checklist and notify Slack.")

    assert engine.call_count == 2
    assert len(delegations) == 2
    assert result.metadata["chief"]["action"] == "complete"
    assert result.metadata["chief"]["status"] == "partial"
    assert "did not" in result.content
    assert result.metadata["chief"]["followups_needed"], (
        "partial result should surface a follow-up action"
    )
    # The failed child should be visible as a failed ToolResult
    failed = [
        r
        for r in result.tool_results
        if r.tool_name == "chief.delegate" and not r.success
    ]
    assert len(failed) == 1


# ---------------------------------------------------------------------------
# Parser-error recovery
# ---------------------------------------------------------------------------


def test_chief_execute_direct_invokes_local_tool():
    """execute_direct should dispatch through the chief's own tool executor."""
    import json as _json

    from openjarvis.agents.orchestrator import OrchestratorAgent
    from openjarvis.core.types import ToolResult
    from openjarvis.tools._stubs import BaseTool, ToolSpec

    captured: list = []

    class _StubTool(BaseTool):
        tool_id = "stub_create"

        @property
        def spec(self) -> ToolSpec:
            return ToolSpec(
                name="stub_create",
                description="Stub creator.",
                parameters={
                    "type": "object",
                    "properties": {"name": {"type": "string"}},
                },
            )

        def execute(self, **params) -> ToolResult:
            captured.append(params)
            return ToolResult(
                tool_name="stub_create",
                content=f"created:{params.get('name', '?')}",
                success=True,
            )

    exec_response = {
        "content": _json.dumps(
            {
                "action": "execute_direct",
                "reason": "single deterministic call",
                "tool_calls": [
                    {"name": "stub_create", "arguments": {"name": "Jarvis"}}
                ],
            }
        )
    }
    complete_response = {
        "content": _json.dumps(
            {
                "action": "complete",
                "reason": "tool ran",
                "final_report": {
                    "status": "completed",
                    "summary": "Created Jarvis.",
                },
            }
        )
    }
    engine = FakeEngine([exec_response, complete_response])

    agent = OrchestratorAgent(
        engine=engine,
        model="fake-model",
        mode="chief",
        max_turns=4,
        tools=[_StubTool()],
    )
    result = agent.run("Create a project called Jarvis.")

    assert engine.call_count == 2
    assert len(captured) == 1
    assert captured[0] == {"name": "Jarvis"}
    assert result.metadata["chief"]["action"] == "complete"
    assert "Created Jarvis." in result.content
    assert any(tr.tool_name == "stub_create" for tr in result.tool_results)


def test_chief_execute_direct_unavailable_tool_reports_failure():
    """If the chief asks for a tool it doesn't have, that's a soft failure."""
    import json as _json

    from openjarvis.agents.orchestrator import OrchestratorAgent

    exec_response = {
        "content": _json.dumps(
            {
                "action": "execute_direct",
                "reason": "wrong tool",
                "tool_calls": [
                    {"name": "no_such_tool", "arguments": {}}
                ],
            }
        )
    }
    fail_response = {
        "content": _json.dumps(
            {
                "action": "fail",
                "reason": "tool was unavailable",
            }
        )
    }
    engine = FakeEngine([exec_response, fail_response])
    agent = OrchestratorAgent(
        engine=engine,
        model="fake-model",
        mode="chief",
        max_turns=4,
        tools=[],
    )
    result = agent.run("Anything.")
    assert engine.call_count == 2
    assert result.metadata["chief"]["action"] == "fail"
    failed = [
        tr for tr in result.tool_results
        if tr.tool_name == "no_such_tool" and not tr.success
    ]
    assert len(failed) == 1


def test_parse_failure_triggers_one_repair_then_fails():
    """First response is invalid; the agent gets exactly one repair turn."""
    bad = {"content": "not JSON at all, just prose."}
    still_bad = {"content": "{ still not actually JSON"}
    agent, engine, _ = _chief([bad, still_bad])

    result = agent.run("Anything.")

    assert engine.call_count == 2
    assert "could not produce a valid action" in result.content
    assert result.metadata["chief"]["action"] == "parse_failed"


def test_parse_failure_recovers_on_repair_turn():
    """First response is invalid; second response is a valid complete."""
    bad = {"content": "prose only"}
    good = {
        "content": json.dumps(
            {
                "action": "complete",
                "reason": "ok after repair",
                "final_report": {"status": "completed", "summary": "recovered"},
            }
        )
    }
    agent, engine, _ = _chief([bad, good])

    result = agent.run("Anything.")

    assert engine.call_count == 2
    assert result.metadata["chief"]["action"] == "complete"
    assert result.content == "recovered"


# ---------------------------------------------------------------------------
# Tool narrowing
# ---------------------------------------------------------------------------


def test_chief_forwards_tools_allowed_to_delegate_fn():
    """tools_allowed on a Delegation reaches the delegation callable."""
    captured: list = []

    def fake_delegate(agent_id, message, *, tools_allowed=None):
        captured.append({
            "agent_id": agent_id,
            "tools_allowed": tools_allowed,
        })
        return "ok"

    delegate_response = {
        "content": json.dumps(
            {
                "action": "delegate",
                "reason": "scoped",
                "delegations": [
                    {
                        "agent_name_or_id": "worker.research.a",
                        "message": "search for X",
                        "tools_allowed": ["web_search"],
                    },
                    {
                        "agent_name_or_id": "worker.research.b",
                        "message": "reason from prompt only",
                        "tools_allowed": [],
                    },
                ],
            }
        )
    }
    complete_response = {
        "content": json.dumps(
            {
                "action": "complete",
                "reason": "done",
                "final_report": {"status": "completed", "summary": "ok"},
            }
        )
    }

    agent, _engine, _ = _chief(
        [delegate_response, complete_response],
        delegate_fn=fake_delegate,
    )
    agent.run("Anything.")

    assert len(captured) == 2
    assert captured[0]["tools_allowed"] == ["web_search"]
    assert captured[1]["tools_allowed"] == []


def test_chief_omits_tools_allowed_when_unset():
    """When the chief does not set tools_allowed, the delegate sees None."""
    captured: list = []

    def fake_delegate(agent_id, message, *, tools_allowed=None):
        captured.append(tools_allowed)
        return "ok"

    delegate_response = {
        "content": json.dumps(
            {
                "action": "delegate",
                "reason": "default toolset",
                "delegations": [
                    {
                        "agent_name_or_id": "worker.research.a",
                        "message": "anything",
                    }
                ],
            }
        )
    }
    complete_response = {
        "content": json.dumps(
            {
                "action": "complete",
                "reason": "done",
                "final_report": {"status": "completed", "summary": "ok"},
            }
        )
    }

    agent, _engine, _ = _chief(
        [delegate_response, complete_response],
        delegate_fn=fake_delegate,
    )
    agent.run("Anything.")

    assert captured == [None]
