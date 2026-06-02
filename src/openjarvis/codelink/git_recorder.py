"""Record the HEAD commit of a repo as a CodeChangeLink.

Reuses ``tools.git_tool._run_git`` so it shares the project's git plumbing.
"""

from __future__ import annotations

from typing import Optional

from openjarvis.codelink.store import CodeChangeLink, CodeLinkStore


def record_head_commit(
    store: CodeLinkStore,
    repo_path: str,
    *,
    task_id: str = "",
    agent_id: str = "",
    project_id: str = "",
    now: Optional[float] = None,
) -> Optional[CodeChangeLink]:
    """Read the repo's HEAD commit and persist it as a CodeChangeLink.

    Returns None if the repo or commit cannot be read.
    """
    from openjarvis.tools.git_tool import _run_git

    fmt = "%H%n%at%n%s"
    show = _run_git(["git", "show", "-s", f"--format={fmt}", "HEAD"], cwd=repo_path)
    if not show.success:
        return None
    lines = show.content.splitlines()
    if len(lines) < 1 or not lines[0].strip():
        return None
    sha = lines[0].strip()
    committed_at: Optional[float]
    try:
        committed_at = float(lines[1].strip()) if len(lines) > 1 else None
    except ValueError:
        committed_at = None
    message = lines[2].strip() if len(lines) > 2 else ""

    files: list[str] = []
    insertions = 0
    deletions = 0
    numstat = _run_git(["git", "show", "--numstat", "--format=", "HEAD"], cwd=repo_path)
    if numstat.success:
        for row in numstat.content.splitlines():
            parts = row.split("\t")
            if len(parts) == 3:
                add, dele, path = parts
                if path.strip():
                    files.append(path.strip())
                if add.isdigit():
                    insertions += int(add)
                if dele.isdigit():
                    deletions += int(dele)

    return store.record_commit(
        commit_sha=sha,
        repo_path=repo_path,
        task_id=task_id,
        agent_id=agent_id,
        project_id=project_id,
        message=message,
        files_changed=files,
        insertions=insertions,
        deletions=deletions,
        committed_at=committed_at,
        now=now,
    )
