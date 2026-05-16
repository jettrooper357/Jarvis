"""Project management: SQLite-backed projects, tasks, subtasks and notes.

This is the canonical store for the project-management feature. Both the
web UI (via the projects API router) and AI agents (via the
``project_management`` connector) read from here, so project data stays a
single source of truth instead of a browser-local silo.
"""

from openjarvis.projects.store import ProjectStore

__all__ = ["ProjectStore"]
