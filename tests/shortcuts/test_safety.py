"""Tests for the regex backtracking guard and recursive-firing guard."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from openjarvis.shortcuts import (
    ShortcutRegistry,
    suppress_recursive_match,
    try_shortcut,
)
from openjarvis.shortcuts._stubs import PatternSpec, RawResult, Resolver, ShortcutRule
from openjarvis.shortcuts.matcher import (
    _MATCH_TIMEOUT_SECONDS,
    drain_unsafe_rule_ids,
)


def _ts() -> str:
    return datetime.now(timezone.utc).isoformat()


class _NeverResolver(Resolver):
    kind = "tool"

    def resolve(self, target_id, args):  # pragma: no cover — should never run
        return RawResult(content="should-not-reach", success=True)


class _OkResolver(Resolver):
    kind = "tool"

    def __init__(self) -> None:
        self.calls = 0

    def resolve(self, target_id, args):
        self.calls += 1
        return RawResult(content="ok", success=True)


@pytest.fixture()
def registry(tmp_path: Path) -> ShortcutRegistry:
    drain_unsafe_rule_ids()
    return ShortcutRegistry(db_path=tmp_path / "sc.db")


def test_recursive_guard_blocks_inner_match(registry):
    rule = ShortcutRule(
        id="r1",
        name="hi",
        patterns=[PatternSpec("phrase", "hello")],
        target_kind="tool",
        target_id="get_news",
        created_at=_ts(),
        updated_at=_ts(),
    )
    registry.upsert(rule)
    resolver = _OkResolver()

    inside = try_shortcut(
        "hello there",
        registry=registry,
        resolvers={"tool": resolver},
    )
    assert inside.matched is True

    with suppress_recursive_match():
        outcome = try_shortcut(
            "hello there",
            registry=registry,
            resolvers={"tool": _NeverResolver()},
        )
    assert outcome.matched is False
    assert outcome.handled is False


def test_flagged_unsafe_rule_is_disabled_on_next_call(registry, monkeypatch):
    # Validate the drain → disable flow without relying on the timing of
    # a real catastrophic pattern (which varies by Python build / OS).
    # We monkeypatch the matcher's safe-search so it always reports the
    # rule as unsafe; ``try_shortcut`` should then return no-match and
    # flip the rule to ``enabled=False``.
    from openjarvis.shortcuts import matcher as matcher_mod

    rule = ShortcutRule(
        id="bad",
        name="evil",
        patterns=[PatternSpec("regex", r"^(a+)+$")],
        target_kind="tool",
        target_id="get_news",
        created_at=_ts(),
        updated_at=_ts(),
    )
    registry.upsert(rule)

    def fake_safe_search(regex, haystack, rule_id, *, enforce_timeout):
        matcher_mod._flag_unsafe(rule_id)
        return None

    monkeypatch.setattr(matcher_mod, "_safe_search", fake_safe_search)

    outcome = try_shortcut(
        "aaaa!",
        registry=registry,
        resolvers={"tool": _OkResolver()},
    )
    assert outcome.matched is False
    refreshed = registry.get("bad")
    assert refreshed is not None
    assert refreshed.enabled is False


def test_timeout_constant_is_short_enough_to_be_meaningful():
    # Pure sanity check — keep the budget under one second so a hung
    # match cannot tank an interactive request.
    assert 0 < _MATCH_TIMEOUT_SECONDS < 1.0
