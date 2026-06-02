"""Life Manager subsystem.

Durable storage for life domains (work/church/health/home/…) and recurring
routines with due-tracking. Append-only-ish SQLite history; gives the Life
Manager agents a real data model instead of shoehorning into project tasks.
"""

from __future__ import annotations
