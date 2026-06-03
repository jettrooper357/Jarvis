"""Controlled Autonomy subsystem.

Rollback history (record + undo reversible autonomous actions via a handler
registry) and audit reports over the Persisted Event Log. Additive; does not
touch the scheduler or approval-gating execution paths.
"""

from __future__ import annotations
