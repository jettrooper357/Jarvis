from __future__ import annotations

from openjarvis.autonomy.handlers import (
    get_undo_handler,
    has_handler,
    register_undo_handler,
)


def test_file_write_handler_restores_prior_content(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("new", encoding="utf-8")
    handler = get_undo_handler("file_write")
    assert handler is not None
    handler({"path": str(f), "prior_content": "old"})
    assert f.read_text(encoding="utf-8") == "old"


def test_file_write_handler_deletes_newly_created(tmp_path):
    f = tmp_path / "new.txt"
    f.write_text("created", encoding="utf-8")
    get_undo_handler("file_write")({"path": str(f), "prior_content": None})
    assert not f.exists()


def test_irreversible_types_have_no_handler():
    assert has_handler("email") is False
    assert has_handler("deploy") is False
    assert get_undo_handler("email") is None


def test_register_and_lookup_custom_handler():
    seen = {}
    register_undo_handler("unit_test_kind", lambda payload: seen.update(payload))
    assert has_handler("unit_test_kind") is True
    get_undo_handler("unit_test_kind")({"x": 1})
    assert seen == {"x": 1}
