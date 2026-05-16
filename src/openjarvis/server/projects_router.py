"""FastAPI router for /v1/projects — project / task / note management.

Backed by :class:`openjarvis.projects.store.ProjectStore` (SQLite) so the
UI and AI agents share one source of truth.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

_store = None  # lazy singleton


def _get_store():
    global _store
    if _store is None:
        from openjarvis.projects.store import ProjectStore

        _store = ProjectStore()
    return _store


def _ai_summary(engine: Any, model: str, text: str) -> Optional[str]:
    """Best-effort LLM summary of a project; returns None on any failure."""
    if engine is None:
        return None
    try:
        from openjarvis.core.types import Message

        messages = [
            Message(
                role="system",
                content=(
                    "You are a project management assistant. Summarize the "
                    "project's status in 3-5 sentences: overall health, "
                    "what's progressing, risks/blockers, and the single most "
                    "important next action. Be concrete and concise."
                ),
            ),
            Message(role="user", content=text[:6000]),
        ]
        result = engine.generate(
            messages, model=model, temperature=0.3, max_tokens=400
        )
        content = (result or {}).get("content", "").strip()
        return content or None
    except Exception as exc:  # pragma: no cover - engine optional
        logger.debug("AI summary failed: %s", exc)
        return None


def create_projects_router():
    """Return an APIRouter exposing project-management CRUD + analytics."""
    from fastapi import APIRouter, HTTPException, Request

    router = APIRouter(prefix="/v1/projects", tags=["projects"])

    # --- analytics (declared before /{project_id}) ---------------------

    @router.get("/dashboard")
    async def dashboard():
        return _get_store().dashboard()

    # --- projects ------------------------------------------------------

    @router.get("")
    async def list_projects():
        return {"projects": _get_store().list_projects()}

    @router.post("")
    async def create_project(request: Request):
        body = await request.json()
        if not isinstance(body, dict):
            raise HTTPException(400, "Body must be a JSON object")
        return _get_store().create_project(**body)

    @router.get("/{project_id}")
    async def get_project(project_id: str):
        p = _get_store().get_project(project_id)
        if p is None:
            raise HTTPException(404, f"Project '{project_id}' not found")
        return p

    @router.put("/{project_id}")
    async def update_project(project_id: str, request: Request):
        body = await request.json()
        try:
            return _get_store().update_project(project_id, **(body or {}))
        except KeyError:
            raise HTTPException(404, f"Project '{project_id}' not found")

    @router.delete("/{project_id}")
    async def delete_project(project_id: str):
        _get_store().delete_project(project_id)
        return {"deleted": True, "id": project_id}

    @router.post("/{project_id}/ai-summary")
    async def ai_summary(project_id: str, request: Request):
        store = _get_store()
        if store.get_project(project_id) is None:
            raise HTTPException(404, f"Project '{project_id}' not found")
        docs = [d for d in store.export_documents() if d["project_id"] == project_id]
        text = docs[0]["content"] if docs else ""
        engine = getattr(request.app.state, "engine", None)
        model = getattr(request.app.state, "model", "") or ""
        summary = _ai_summary(engine, model, text)
        if summary is None:
            # Deterministic fallback so the UI always gets something useful.
            tasks = store.list_tasks(project_id)
            blocked = [t for t in tasks if t.get("status") == "Blocked"]
            open_tasks = [
                t
                for t in tasks
                if t.get("status") not in ("Done", "Cancelled")
            ]
            p = store.get_project(project_id)
            summary = (
                f"{p['name']} is {p.get('progress', 0)}% complete with "
                f"{len(open_tasks)} open task(s)"
                + (
                    f" and {len(blocked)} blocked."
                    if blocked
                    else "."
                )
                + " (AI engine unavailable — heuristic summary.)"
            )
        return {"project_id": project_id, "summary": summary}

    # --- tasks ---------------------------------------------------------

    @router.get("/{project_id}/tasks")
    async def list_tasks(project_id: str):
        return {"tasks": _get_store().list_tasks(project_id)}

    @router.post("/{project_id}/tasks")
    async def create_task(project_id: str, request: Request):
        body = await request.json()
        try:
            return _get_store().create_task(project_id, **(body or {}))
        except KeyError:
            raise HTTPException(404, f"Project '{project_id}' not found")

    @router.put("/tasks/{task_id}")
    async def update_task(task_id: str, request: Request):
        body = await request.json()
        try:
            return _get_store().update_task(task_id, **(body or {}))
        except KeyError:
            raise HTTPException(404, f"Task '{task_id}' not found")

    @router.delete("/tasks/{task_id}")
    async def delete_task(task_id: str):
        _get_store().delete_task(task_id)
        return {"deleted": True, "id": task_id}

    # --- notes ---------------------------------------------------------

    @router.get("/tasks/{task_id}/notes")
    async def list_notes(task_id: str):
        return {"notes": _get_store().list_notes(task_id)}

    @router.post("/tasks/{task_id}/notes")
    async def add_note(task_id: str, request: Request):
        body = await request.json()
        try:
            return _get_store().add_note(task_id, **(body or {}))
        except KeyError:
            raise HTTPException(404, f"Task '{task_id}' not found")

    @router.put("/notes/{note_id}")
    async def update_note(note_id: str, request: Request):
        body = await request.json()
        try:
            return _get_store().update_note(note_id, **(body or {}))
        except KeyError:
            raise HTTPException(404, f"Note '{note_id}' not found")

    @router.delete("/notes/{note_id}")
    async def delete_note(note_id: str):
        _get_store().delete_note(note_id)
        return {"deleted": True, "id": note_id}

    return router


__all__ = ["create_projects_router"]
