"""Phase 2A — canonical TaskStatus enum + legacy mapper tests."""

from __future__ import annotations

import pytest

from openjarvis.core.types import TaskStatus, map_legacy_status, to_legacy_status


@pytest.mark.parametrize(
    "legacy, expected",
    [
        ("pending", TaskStatus.RECEIVED),
        ("active", TaskStatus.IN_PROGRESS),
        ("completed", TaskStatus.COMPLETED),
        ("failed", TaskStatus.FAILED),
    ],
)
def test_legacy_to_canonical(legacy: str, expected: TaskStatus) -> None:
    assert map_legacy_status(legacy) is expected


def test_canonical_strings_round_trip() -> None:
    for status in TaskStatus:
        assert map_legacy_status(status.value) is status


def test_taskstatus_instance_is_returned_as_is() -> None:
    assert map_legacy_status(TaskStatus.BLOCKED) is TaskStatus.BLOCKED


def test_unknown_value_falls_back_to_received() -> None:
    assert map_legacy_status("not_a_real_status") is TaskStatus.RECEIVED
    assert map_legacy_status(None) is TaskStatus.RECEIVED
    assert map_legacy_status("") is TaskStatus.RECEIVED


@pytest.mark.parametrize(
    "canonical, legacy",
    [
        (TaskStatus.RECEIVED, "pending"),
        (TaskStatus.TRIAGED, "pending"),
        (TaskStatus.PLANNED, "pending"),
        (TaskStatus.DELEGATED, "active"),
        (TaskStatus.IN_PROGRESS, "active"),
        (TaskStatus.BLOCKED, "active"),
        (TaskStatus.AWAITING_INPUT, "active"),
        (TaskStatus.AWAITING_APPROVAL, "active"),
        (TaskStatus.COMPLETED, "completed"),
        (TaskStatus.FAILED, "failed"),
        (TaskStatus.CANCELLED, "failed"),
    ],
)
def test_to_legacy_status_mapping(canonical: TaskStatus, legacy: str) -> None:
    assert to_legacy_status(canonical) == legacy


def test_to_legacy_status_from_legacy_string_is_idempotent() -> None:
    for legacy in ("pending", "active", "completed", "failed"):
        assert to_legacy_status(legacy) == legacy


def test_to_legacy_status_unknown_falls_back_to_pending() -> None:
    # Unknown → RECEIVED → "pending" in legacy
    assert to_legacy_status("???") == "pending"
