from __future__ import annotations

from openjarvis.autonomy.rollback_store import (
    ReversibleAction,
    RollbackStore,
)


def _store(tmp_path):
    return RollbackStore(db_path=str(tmp_path / "auto.db"))


def test_record_reversible_is_active(tmp_path):
    store = _store(tmp_path)
    a = store.record(
        action_type="file_write",
        summary="wrote a.txt",
        undo_payload={"path": "/tmp/a.txt", "prior_content": "old"},
        agent_id="dev",
        now=1000.0,
    )
    assert isinstance(a, ReversibleAction)
    assert a.status == "active"  # file_write has a handler
    assert a.action_type == "file_write"
    assert a.created_at == 1000.0
    got = store.get(a.id)
    assert got is not None
    assert got.undo_payload == {"path": "/tmp/a.txt", "prior_content": "old"}
    hist = store.history(a.id)
    assert hist[0]["to_status"] == "active"
    store.close()


def test_record_irreversible_type_is_marked(tmp_path):
    store = _store(tmp_path)
    a = store.record(action_type="email", summary="sent mail", now=1.0)
    assert a.status == "irreversible"  # no handler for email
    store.close()


def test_record_reversible_false_is_irreversible(tmp_path):
    store = _store(tmp_path)
    a = store.record(action_type="file_write", summary="x", reversible=False, now=1.0)
    assert a.status == "irreversible"
    store.close()


def test_list_filters(tmp_path):
    store = _store(tmp_path)
    store.record(action_type="file_write", summary="a", agent_id="x", now=1.0)
    store.record(action_type="email", summary="b", agent_id="y", now=2.0)
    assert len(store.list()) == 2
    assert len(store.list(action_type="file_write")) == 1
    assert len(store.list(status="irreversible")) == 1
    assert len(store.list(agent_id="x")) == 1
    assert store.list()[0].summary == "b"  # newest first
    store.close()


def test_record_requires_action_type(tmp_path):
    import pytest

    store = _store(tmp_path)
    with pytest.raises(ValueError):
        store.record(action_type="  ", summary="x")
    store.close()


def test_revert_file_write_restores_bytes(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("new", encoding="utf-8")
    store = _store(tmp_path)
    a = store.record(
        action_type="file_write",
        summary="wrote a",
        undo_payload={"path": str(f), "prior_content": "old"},
        now=1.0,
    )
    reverted = store.revert(a.id, note="undo", now=2.0)
    assert reverted.status == "reverted"
    assert reverted.reverted_at == 2.0
    assert f.read_text(encoding="utf-8") == "old"
    states = [e["to_status"] for e in store.history(a.id)]
    assert states == ["active", "reverted"]
    store.close()


def test_revert_irreversible_returns_clear_status(tmp_path):
    store = _store(tmp_path)
    a = store.record(action_type="email", summary="sent", now=1.0)
    result = store.revert(a.id, now=2.0)
    assert result.status == "irreversible"
    assert result.reverted_at is None
    store.close()


def test_revert_missing_raises(tmp_path):
    import pytest

    store = _store(tmp_path)
    with pytest.raises(Exception):
        store.revert("nope")
    store.close()


def test_revert_already_reverted_raises(tmp_path):
    import pytest

    f = tmp_path / "a.txt"
    f.write_text("new", encoding="utf-8")
    store = _store(tmp_path)
    a = store.record(
        action_type="file_write",
        summary="x",
        undo_payload={"path": str(f), "prior_content": "old"},
        now=1.0,
    )
    store.revert(a.id, now=2.0)
    with pytest.raises(Exception):
        store.revert(a.id, now=3.0)
    store.close()


def test_revert_handler_failure_marks_failed(tmp_path):
    import pytest

    store = _store(tmp_path)
    # file_write with a path that cannot be written (a directory) -> handler raises
    a = store.record(
        action_type="file_write",
        summary="bad",
        undo_payload={"path": str(tmp_path), "prior_content": "x"},
        now=1.0,
    )
    with pytest.raises(Exception):
        store.revert(a.id, now=2.0)
    after = store.get(a.id)
    assert after.status == "failed"
    assert after.revert_note
    store.close()
