"""Persisted Event Log subsystem.

Durable, append-only SQLite storage behind the in-memory ``EventBus``. The bus
remains the live source of truth; this store is queryable history for
traceability, audit, and the activity feed.
"""

from __future__ import annotations
