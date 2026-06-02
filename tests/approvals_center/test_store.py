from __future__ import annotations

from openjarvis.approvals_center.store import (
    ActionApproval,
    ActionApprovalStore,
)


def _store(tmp_path):
    return ActionApprovalStore(db_path=str(tmp_path / "aa.db"))


def test_request_and_get(tmp_path):
    store = _store(tmp_path)
    a = store.request(
        action_type="email",
        summary="Send reply to Nate",
        payload={"to": "nate@example.com", "body": "hi"},
        agent_id="ea",
        task_id="t1",
        project_id="p1",
        requested_by="user",
        now=1000.0,
    )
    assert isinstance(a, ActionApproval)
    assert a.state == "pending"
    assert a.action_type == "email"
    assert a.revision == 0
    assert a.requested_at == 1000.0
    fetched = store.get(a.id)
    assert fetched is not None
    assert fetched.payload == {"to": "nate@example.com", "body": "hi"}
    assert fetched.project_id == "p1"
    hist = store.history(a.id)
    assert len(hist) == 1
    assert hist[0]["to_state"] == "pending"
    store.close()


def test_request_requires_action_type_and_summary(tmp_path):
    import pytest

    store = _store(tmp_path)
    with pytest.raises(ValueError):
        store.request(action_type="  ", summary="x")
    with pytest.raises(ValueError):
        store.request(action_type="email", summary="  ")
    store.close()


def test_list_filters_and_ordering(tmp_path):
    store = _store(tmp_path)
    store.request(action_type="email", summary="a", agent_id="ea", now=1.0)
    store.request(action_type="code", summary="b", project_id="p1", now=2.0)
    assert len(store.list()) == 2
    assert len(store.list(action_type="email")) == 1
    assert len(store.list(project_id="p1")) == 1
    assert store.list()[0].summary == "b"  # newest first
    store.close()


def test_approve_and_reject_are_terminal(tmp_path):
    import pytest

    store = _store(tmp_path)
    a = store.request(action_type="deploy", summary="ship", now=1.0)
    approved = store.approve(a.id, resolved_by="user", reason="lgtm", now=2.0)
    assert approved.state == "approved"
    assert approved.resolved_by == "user"
    assert approved.resolved_at == 2.0
    with pytest.raises(Exception):
        store.reject(a.id, resolved_by="user")
    states = [e["to_state"] for e in store.history(a.id)]
    assert states == ["pending", "approved"]
    store.close()


def test_defer_ask_modify_reopen(tmp_path):
    store = _store(tmp_path)
    a = store.request(action_type="plan", summary="shift timeline", now=1.0)

    deferred = store.defer(a.id, remind_at=999.0, now=2.0)
    assert deferred.state == "deferred"
    assert deferred.remind_at == 999.0
    reopened = store.reopen(a.id, now=3.0)
    assert reopened.state == "pending"

    asked = store.ask(a.id, question="which milestone?", now=4.0)
    assert asked.state == "needs_info"
    assert asked.followup_question == "which milestone?"
    store.reopen(a.id, now=5.0)

    modified = store.modify(a.id, new_payload={"shift_days": 3}, now=6.0)
    assert modified.state == "modified"
    assert modified.revision == 1
    assert modified.payload == {"shift_days": 3}
    store.close()


def test_missing_id_raises(tmp_path):
    import pytest

    store = _store(tmp_path)
    with pytest.raises(Exception):
        store.approve("nope")
    store.close()


def test_cannot_reopen_terminal(tmp_path):
    import pytest

    store = _store(tmp_path)
    a = store.request(action_type="file", summary="rm x", now=1.0)
    store.reject(a.id, now=2.0)
    with pytest.raises(Exception):
        store.reopen(a.id, now=3.0)
    store.close()
