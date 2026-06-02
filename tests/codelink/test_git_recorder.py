from __future__ import annotations

import shutil
import subprocess

import pytest

from openjarvis.codelink.git_recorder import record_head_commit
from openjarvis.codelink.store import CodeLinkStore

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")


def _git(repo, *args):
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


def test_record_head_commit(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "Tester")
    (repo / "a.py").write_text("print('hi')\n", encoding="utf-8")
    _git(repo, "add", "a.py")
    _git(repo, "commit", "-m", "add a.py")

    store = CodeLinkStore(db_path=str(tmp_path / "cl.db"))
    link = record_head_commit(store, str(repo), task_id="t1")
    assert link is not None
    assert len(link.commit_sha) >= 7
    assert link.task_id == "t1"
    assert "a.py" in link.files_changed
    assert link.insertions >= 1
    assert "add a.py" in link.message
    store.close()


def test_record_head_commit_bad_repo_returns_none(tmp_path):
    store = CodeLinkStore(db_path=str(tmp_path / "cl.db"))
    assert record_head_commit(store, str(tmp_path / "nope")) is None
    store.close()
