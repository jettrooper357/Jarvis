"""Task–Code Linkage subsystem.

Records file changes (FileEvent) and commits (CodeChangeLink) and links them
to tasks/agents/projects, so the system can answer why a file changed, which
task code belongs to, and who changed it. Append-only SQLite history; an
optional filesystem watcher degrades gracefully when ``watchdog`` is absent.
"""

from __future__ import annotations
