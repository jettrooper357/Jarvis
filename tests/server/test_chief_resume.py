"""Chief checkpoint + resume lifecycle tests.

Validates the new pause-on-ask_user behaviour:

1. When the chief emits ``action=ask_user``, the runtime stores a
   checkpoint and flips the managed agent's status to
   ``input_required`` instead of silently dropping the run.
2. ``ManagedAgentRuntime.resume(agent_id, answer)`` reconstructs the
   chief's mid-run state, appends the user's answer, and lets the chief
   continue.
3. The resumed run's trace shares the original ``run_id`` and points at
   the original chief trace via ``parent_trace_id`` so the whole call
   tree groups together.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

import pytest

from openjarvis.agents.manager import AgentManager
from openjarvis.server.managed_agent_runtime import ManagedAgentRuntime
from openjarvis.traces.store import TraceStore
from tests.agents.fake_engine import FakeEngine


class _StubProjectStore:
    """Minimal project store to satisfy AgentManager's hard-link rules."""

    _DUMMY_TASK: Dict[str, Any] = {
        "id": "proj_task_dummy",
        "project_id": "proj_dummy",
        "title": "Dummy",
        "parent_task_id": None,
        "status": "Backlog",
    }
    _DUMMY_PROJECT: Dict[str, Any] = {"id": "proj_dummy", "name": "Dummy"}

    def get_task(self, task_id: str) -> Dict[str, Any]:
        return dict(self._DUMMY_TASK, id=task_id)

    def list_tasks(self, project_id: str) -> List[Dict[str, Any]]:
        return [dict(self._DUMMY_TASK)]

    def list_projects(self) -> List[Dict[str, Any]]:
        return [dict(self._DUMMY_PROJECT)]

    def get_project(self, project_id: str) -> Dict[str, Any]:
        return dict(self._DUMMY_PROJECT)

    def create_project(self, **kwargs: Any) -> Dict[str, Any]:
        return dict(self._DUMMY_PROJECT)

    def create_task(self, project_id: str, **kwargs: Any) -> Dict[str, Any]:
        out = dict(self._DUMMY_TASK)
        out["project_id"] = project_id
        return out

    def update_task(self, task_id: str, **kwargs: Any) -> Dict[str, Any]:
        return dict(self._DUMMY_TASK, id=task_id, **kwargs)


@pytest.fixture
def env(tmp_path: Path):
    manager = AgentManager(
        db_path=str(tmp_path / "agents.db"),
        project_store=_StubProjectStore(),
    )
    trace_store = TraceStore(str(tmp_path / "traces.db"))
    chief = manager.create_agent(
        name="Resume Chief",
        agent_type="monitor_operative",
        org_role="chief orchestrator",
        config={
            "model": "fake-model",
            "orchestrator_mode": "chief",
            "max_turns": 3,
            "temperature": 0.0,
            "max_tokens": 256,
        },
    )
    yield {"manager": manager, "trace_store": trace_store, "chief": chief}
    manager.close()
    trace_store.close()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


_ASK_USER = json.dumps(
    {
        "action": "ask_user",
        "reason": "Need a target date to plan the rollout.",
        "followup_question": {
            "question": "When should the rollout go live?",
            "reason": "Cannot schedule without a target date.",
            "expected_response_type": "free_text",
        },
    }
)

_COMPLETE = json.dumps(
    {
        "action": "complete",
        "reason": "User supplied date; plan finalized.",
        "final_report": {
            "status": "completed",
            "summary": "Rollout scheduled for the date the user provided.",
        },
    }
)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_ask_user_writes_checkpoint_and_sets_status(env):
    engine = FakeEngine([{"content": _ASK_USER}])
    runtime = ManagedAgentRuntime(
        env["manager"], engine,
        trace_store=env["trace_store"], default_model="fake-model",
    )

    response = runtime.run(env["chief"]["id"], "Plan the rollout.")

    assert "When should the rollout go live?" in response

    agent = env["manager"].get_agent(env["chief"]["id"])
    assert agent["status"] == "input_required"

    checkpoint = env["manager"].get_latest_checkpoint(env["chief"]["id"])
    assert checkpoint is not None
    conv = checkpoint["conversation_state"]
    tool_state = checkpoint["tool_state"]

    assert any(
        m.get("role") == "user" and "Plan the rollout" in m.get("content", "")
        for m in conv["messages"]
    )
    assert tool_state["already_delegated"] is False
    assert tool_state["turns"] == 1
    assert tool_state["question"]["question"] == "When should the rollout go live?"
    assert tool_state["run_id"], "run_id must be persisted for resume continuity"


def test_resume_continues_from_checkpoint(env):
    engine = FakeEngine([{"content": _ASK_USER}, {"content": _COMPLETE}])
    runtime = ManagedAgentRuntime(
        env["manager"], engine,
        trace_store=env["trace_store"], default_model="fake-model",
    )

    runtime.run(env["chief"]["id"], "Plan the rollout.")
    assert env["manager"].get_agent(env["chief"]["id"])["status"] == "input_required"

    response = runtime.resume(env["chief"]["id"], "Launch on 2026-06-01.")

    assert "Rollout scheduled" in response
    final_status = env["manager"].get_agent(env["chief"]["id"])["status"]
    assert final_status == "idle"
    # Engine should have been called exactly twice across the two phases.
    assert engine.call_count == 2


def test_resume_trace_links_to_original_run(env):
    engine = FakeEngine([{"content": _ASK_USER}, {"content": _COMPLETE}])
    runtime = ManagedAgentRuntime(
        env["manager"], engine,
        trace_store=env["trace_store"], default_model="fake-model",
    )

    runtime.run(env["chief"]["id"], "Plan the rollout.")
    runtime.resume(env["chief"]["id"], "Launch on 2026-06-01.")

    store = env["trace_store"]
    rows = store._fetchall()
    traces = [store._row_to_trace(r) for r in rows]
    assert len(traces) == 2, f"expected 2 traces, got {len(traces)}"

    # Find original (no parent) and resume (has parent)
    roots = [t for t in traces if t.parent_trace_id is None]
    resumes = [t for t in traces if t.parent_trace_id is not None]
    assert len(roots) == 1 and len(resumes) == 1
    original, resumed = roots[0], resumes[0]

    assert resumed.parent_trace_id == original.trace_id
    assert resumed.run_id == original.run_id
    assert resumed.run_id is not None


def test_resume_with_no_checkpoint_raises(env):
    runtime = ManagedAgentRuntime(
        env["manager"], FakeEngine([]),
        trace_store=env["trace_store"], default_model="fake-model",
    )
    with pytest.raises(ValueError, match="No checkpoint"):
        runtime.resume(env["chief"]["id"], "answer with nothing to resume")


_ASK_CREDENTIAL = json.dumps(
    {
        "action": "ask_user",
        "reason": "Need an API token to call the gateway.",
        "followup_question": {
            "question": "Paste your API token.",
            "reason": "Cannot authenticate without it.",
            "expected_response_type": "credential",
        },
    }
)


def test_credential_pause_sets_auth_required_status(env):
    """ask_user with expected_response_type=credential -> status=auth_required."""
    engine = FakeEngine([{"content": _ASK_CREDENTIAL}])
    runtime = ManagedAgentRuntime(
        env["manager"], engine,
        trace_store=env["trace_store"], default_model="fake-model",
    )

    runtime.run(env["chief"]["id"], "Call the gateway.")

    agent = env["manager"].get_agent(env["chief"]["id"])
    assert agent["status"] == "auth_required"
    checkpoint = env["manager"].get_latest_checkpoint(env["chief"]["id"])
    assert checkpoint is not None
    saved_question = checkpoint["tool_state"]["question"]
    assert saved_question["expected_response_type"] == "credential"


def test_credential_resume_redacts_in_agent_messages(env):
    """The long-lived agent_messages log must not store the raw credential."""
    engine = FakeEngine(
        [{"content": _ASK_CREDENTIAL}, {"content": _COMPLETE}]
    )
    runtime = ManagedAgentRuntime(
        env["manager"], engine,
        trace_store=env["trace_store"], default_model="fake-model",
    )

    runtime.run(env["chief"]["id"], "Call the gateway.")
    secret = "sk-redact-me-from-message-store-987654321"
    runtime.resume(env["chief"]["id"], secret)

    messages = env["manager"].list_messages(env["chief"]["id"], limit=50)
    for m in messages:
        assert secret not in (m.get("content") or ""), (
            f"credential leaked into agent_messages row {m.get('id')}"
        )

    # A redacted placeholder should have been written instead so the
    # transcript still records that an answer arrived.
    placeholders = [
        m for m in messages
        if "[credential supplied" in (m.get("content") or "")
    ]
    assert len(placeholders) == 1
    placeholder = placeholders[0]
    assert str(len(secret)) in placeholder["content"]


def test_non_credential_resume_does_not_redact_messages(env):
    """Free-text answers must persist verbatim in agent_messages."""
    engine = FakeEngine(
        [{"content": _ASK_USER}, {"content": _COMPLETE}]
    )
    runtime = ManagedAgentRuntime(
        env["manager"], engine,
        trace_store=env["trace_store"], default_model="fake-model",
    )
    runtime.run(env["chief"]["id"], "Plan it.")
    runtime.resume(env["chief"]["id"], "Launch on 2026-06-01.")

    messages = env["manager"].list_messages(env["chief"]["id"], limit=50)
    contents = [m.get("content") or "" for m in messages]
    assert any("Launch on 2026-06-01." in c for c in contents)
    assert not any("[credential supplied" in c for c in contents)


def test_credential_resume_redacts_answer_in_trace(env):
    """A credential answer must NOT appear verbatim in the trace store."""
    engine = FakeEngine(
        [{"content": _ASK_CREDENTIAL}, {"content": _COMPLETE}]
    )
    runtime = ManagedAgentRuntime(
        env["manager"], engine,
        trace_store=env["trace_store"], default_model="fake-model",
    )

    runtime.run(env["chief"]["id"], "Call the gateway.")
    secret = "sk-this-must-not-leak-into-the-trace-1234567890"
    runtime.resume(env["chief"]["id"], secret)

    store = env["trace_store"]
    rows = store._fetchall()
    for raw in rows:
        trace = store._row_to_trace(raw)
        assert secret not in trace.query, (
            f"credential leaked into trace {trace.trace_id} query"
        )
        assert secret not in trace.result, (
            f"credential leaked into trace {trace.trace_id} result"
        )

    # The resume trace should carry the redaction marker + metadata flag.
    resumed = [
        store._row_to_trace(r) for r in rows
        if store._row_to_trace(r).parent_trace_id is not None
    ]
    assert len(resumed) == 1
    assert resumed[0].query == "[credential redacted]"
    assert resumed[0].metadata.get("credential_response") is True


def test_non_credential_answer_is_not_redacted(env):
    """Free-text answers go through verbatim (not over-redacted)."""
    engine = FakeEngine([{"content": _ASK_USER}, {"content": _COMPLETE}])
    runtime = ManagedAgentRuntime(
        env["manager"], engine,
        trace_store=env["trace_store"], default_model="fake-model",
    )

    runtime.run(env["chief"]["id"], "Plan it.")
    runtime.resume(env["chief"]["id"], "Launch on 2026-06-01.")

    store = env["trace_store"]
    rows = store._fetchall()
    resumed = [
        store._row_to_trace(r) for r in rows
        if store._row_to_trace(r).parent_trace_id is not None
    ]
    assert len(resumed) == 1
    assert resumed[0].query == "Launch on 2026-06-01."
    assert resumed[0].metadata.get("credential_response") is False


def test_credential_in_delegation_scrubs_subordinate_message(env):
    """Chief embeds credential in a delegation; subordinate's log must redact."""
    chief_id = env["chief"]["id"]
    subordinate = env["manager"].create_agent(
        name="Resume Worker",
        agent_type="monitor_operative",
        org_role="researcher",
        config={
            "model": "fake-model",
            "system_prompt": "You are a worker.",
            "max_turns": 1,
            "temperature": 0.0,
        },
        manager_agent_id=chief_id,
    )

    secret = "sk-leak-me-into-the-worker-please-12345"
    chief_delegate = json.dumps(
        {
            "action": "delegate",
            "reason": "Hand the credential to the worker.",
            "delegations": [
                {
                    "agent_name_or_id": subordinate["id"],
                    "message": f"Authenticate with this token: {secret}",
                }
            ],
        }
    )
    worker_reply = {"content": "auth ok"}
    chief_complete = json.dumps(
        {
            "action": "complete",
            "reason": "Worker reported success.",
            "final_report": {
                "status": "completed",
                "summary": "Authenticated.",
            },
        }
    )

    engine = FakeEngine(
        [
            {"content": _ASK_CREDENTIAL},   # turn 1: chief asks for credential
            {"content": chief_delegate},    # resume turn 1: chief delegates
            worker_reply,                   # worker's response
            {"content": chief_complete},    # resume turn 2: chief aggregates
        ]
    )
    runtime = ManagedAgentRuntime(
        env["manager"], engine,
        trace_store=env["trace_store"], default_model="fake-model",
    )

    runtime.run(chief_id, "Authenticate to the gateway.")
    runtime.resume(chief_id, secret)

    # The subordinate's stored user_to_agent should NOT contain the secret.
    sub_messages = env["manager"].list_messages(subordinate["id"], limit=20)
    for m in sub_messages:
        assert secret not in (m.get("content") or ""), (
            f"credential leaked into subordinate message {m.get('id')}"
        )
    placeholders = [
        m for m in sub_messages
        if "[credential redacted]" in (m.get("content") or "")
    ]
    assert len(placeholders) >= 1, (
        "expected the subordinate to have a redacted placeholder in its "
        "message log after the chief embedded a credential in delegation"
    )


def test_credential_resume_passes_token_to_chief_not_raw(env):
    """The chief's inference call must receive the token, never the raw secret."""
    chief_id = env["chief"]["id"]
    seen_messages: list = []

    class _CapturingEngine(FakeEngine):
        def generate(self, messages, **kw):
            seen_messages.append([m.content for m in messages])
            return super().generate(messages, **kw)

    engine = _CapturingEngine(
        [{"content": _ASK_CREDENTIAL}, {"content": _COMPLETE}]
    )
    runtime = ManagedAgentRuntime(
        env["manager"], engine,
        trace_store=env["trace_store"], default_model="fake-model",
    )

    secret = "sk-must-not-reach-the-engine-1234567890"
    runtime.run(chief_id, "Call the gateway.")
    runtime.resume(chief_id, secret)

    # seen_messages[0] = chief's first turn (asking the user)
    # seen_messages[1] = chief's resumed turn (after answer arrives)
    assert len(seen_messages) >= 2
    resume_turn_msgs = seen_messages[1]
    flat = "\n".join(resume_turn_msgs)

    # The chief must NOT see the raw secret in any of the messages it
    # was given for the resumed turn.
    assert secret not in flat, (
        "raw credential leaked into the chief's inference prompt"
    )

    # The chief SHOULD see a vault token in one of the messages.
    assert "[[credential:" in flat, (
        "expected the chief to see a vault token in place of the secret"
    )


def test_vault_is_purged_after_resume(env):
    """No tokens should outlive the resume that created them."""
    engine = FakeEngine(
        [{"content": _ASK_CREDENTIAL}, {"content": _COMPLETE}]
    )
    runtime = ManagedAgentRuntime(
        env["manager"], engine,
        trace_store=env["trace_store"], default_model="fake-model",
    )

    runtime.run(env["chief"]["id"], "Call the gateway.")
    runtime.resume(env["chief"]["id"], "sk-purge-vault-after-resume-1234")

    assert list(runtime._vault.active_runs()) == []


def test_scrubber_purges_after_resume(env):
    """The scrubber state must not outlive the run that registered it."""
    engine = FakeEngine(
        [{"content": _ASK_CREDENTIAL}, {"content": _COMPLETE}]
    )
    runtime = ManagedAgentRuntime(
        env["manager"], engine,
        trace_store=env["trace_store"], default_model="fake-model",
    )

    runtime.run(env["chief"]["id"], "Call the gateway.")
    runtime.resume(env["chief"]["id"], "sk-purge-me-after-resume-1234567890")

    # After resume completes, the scrubber should have no active runs.
    assert list(runtime._scrubber.active_runs()) == []


def test_resume_preserves_already_delegated_flag(env):
    """If the chief paused AFTER delegating, resume must not let it delegate again."""
    delegate_then_pause = json.dumps(
        {
            "action": "delegate",
            "reason": "spawn one specialist",
            "delegations": [
                {
                    "agent_name_or_id": "no-such-agent",
                    "message": "do thing",
                }
            ],
        }
    )
    pause = {"content": _ASK_USER}
    # On resume, a *second* delegate must be blocked by the runtime's guard.
    re_delegate = json.dumps(
        {
            "action": "delegate",
            "reason": "try again",
            "delegations": [
                {"agent_name_or_id": "no-such-agent", "message": "do thing"}
            ],
        }
    )
    repair_complete = json.dumps(
        {
            "action": "complete",
            "reason": "synthesizing",
            "final_report": {"status": "partial", "summary": "stopped here"},
        }
    )
    # This scenario needs headroom for re-delegate + repair + complete
    # after the resume, so raise the chief's max_turns budget.
    env["manager"].update_agent(
        env["chief"]["id"],
        config={
            "model": "fake-model",
            "orchestrator_mode": "chief",
            "max_turns": 6,
            "temperature": 0.0,
            "max_tokens": 256,
        },
    )
    engine = FakeEngine(
        [
            {"content": delegate_then_pause},  # turn 1: delegate
            {"content": _ASK_USER},            # turn 2: ask_user (after delegation)
            {"content": re_delegate},          # turn 3 (resume): tries to redelegate
            {"content": repair_complete},      # turn 4: forced repair -> complete
        ]
    )
    runtime = ManagedAgentRuntime(
        env["manager"], engine,
        trace_store=env["trace_store"], default_model="fake-model",
    )

    runtime.run(env["chief"]["id"], "Plan it.")
    cp = env["manager"].get_latest_checkpoint(env["chief"]["id"])
    assert cp["tool_state"]["already_delegated"] is True

    response = runtime.resume(env["chief"]["id"], "Here is the answer.")
    # Result should be the partial summary, not a successful re-delegation.
    assert "stopped here" in response
