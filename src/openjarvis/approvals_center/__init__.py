"""Approval Center subsystem.

A generalized action-approval queue (arbitrary action types, full
Approve/Reject/Modify/Defer/Ask/Reopen lifecycle), distinct from the
tool-gating ``agents/approvals.py`` store. Append-only SQLite history.
"""

from __future__ import annotations
