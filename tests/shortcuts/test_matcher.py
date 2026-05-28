"""Unit tests for the shortcut matcher."""

from __future__ import annotations

from openjarvis.shortcuts import matcher
from openjarvis.shortcuts._stubs import PatternSpec, ShortcutRule


def _ts(offset: int = 0) -> str:
    return f"2026-05-{27 + offset:02d}T00:00:00+00:00"


def _rule(
    rule_id: str,
    patterns: list[PatternSpec],
    *,
    priority: int = 100,
    target_id: str = "get_news",
    arg_template: dict | None = None,
    match_mode: str = "contains",
    case_sensitive: bool = False,
    enabled: bool = True,
    created_by: str = "user",
    updated_at: str | None = None,
) -> ShortcutRule:
    return ShortcutRule(
        id=rule_id,
        name=rule_id,
        enabled=enabled,
        priority=priority,
        patterns=patterns,
        match_mode=match_mode,
        case_sensitive=case_sensitive,
        target_kind="tool",
        target_id=target_id,
        arg_template=arg_template or {},
        created_at=_ts(),
        updated_at=updated_at or _ts(),
        created_by=created_by,
    )


def test_phrase_matches_case_insensitively_with_punctuation():
    rule = _rule("r1", [PatternSpec("phrase", "what's the news")])
    result = matcher.match("Hey Jarvis, What's the news today?", [rule])
    assert result is not None
    assert result.rule.id == "r1"


def test_phrase_does_not_match_when_disabled():
    rule = _rule("r1", [PatternSpec("phrase", "what's the news")], enabled=False)
    assert matcher.match("what's the news", [rule]) is None


def test_whole_message_mode_rejects_partial():
    rule = _rule(
        "r1",
        [PatternSpec("phrase", "what's the news")],
        match_mode="whole_message",
    )
    assert matcher.match("hey what's the news today", [rule]) is None
    assert matcher.match("What's the news?", [rule]) is not None


def test_regex_named_group_feeds_slots():
    rule = _rule(
        "r1",
        [PatternSpec("regex", r"^\s*news about (?P<topic>.+?)\s*\??$")],
        arg_template={"topic": "{topic}"},
    )
    result = matcher.match("news about taiwan semiconductors?", [rule])
    assert result is not None
    assert result.slots == {"topic": "taiwan semiconductors"}
    assert result.resolved_args == {"topic": "taiwan semiconductors"}


def test_phrase_slot_placeholder_works_like_regex_group():
    rule = _rule(
        "r1",
        [PatternSpec("phrase", "news about {topic}")],
        arg_template={"topic": "{topic}"},
    )
    result = matcher.match("hey, news about climate change please", [rule])
    assert result is not None
    assert result.slots.get("topic") == "climate change please"


def test_priority_wins_on_multi_match():
    low = _rule("low", [PatternSpec("phrase", "news")], priority=50)
    high = _rule("high", [PatternSpec("phrase", "news")], priority=200)
    result = matcher.match("show me the news", [low, high])
    assert result is not None
    assert result.rule.id == "high"


def test_longest_match_wins_at_equal_priority():
    short = _rule("short", [PatternSpec("phrase", "news")], priority=100)
    long = _rule(
        "long",
        [PatternSpec("phrase", "what's the news")],
        priority=100,
    )
    result = matcher.match("hey, what's the news today", [short, long])
    assert result is not None
    assert result.rule.id == "long"


def test_user_authored_wins_over_system_on_full_tie():
    sys_rule = _rule(
        "sys",
        [PatternSpec("phrase", "news")],
        created_by="system",
        updated_at=_ts(),
    )
    user_rule = _rule(
        "user",
        [PatternSpec("phrase", "news")],
        created_by="user",
        updated_at=_ts(),
    )
    result = matcher.match("news", [sys_rule, user_rule])
    assert result is not None
    assert result.rule.id == "user"


def test_no_match_returns_none():
    rule = _rule("r1", [PatternSpec("phrase", "what's the news")])
    assert matcher.match("tell me a joke", [rule]) is None


def test_invalid_regex_is_ignored():
    rule = _rule("bad", [PatternSpec("regex", "[unclosed")])
    good = _rule("good", [PatternSpec("phrase", "hello")])
    result = matcher.match("hello there", [rule, good])
    assert result is not None
    assert result.rule.id == "good"


def test_case_sensitive_flag_respected():
    rule = _rule(
        "r1",
        [PatternSpec("phrase", "News")],
        case_sensitive=True,
    )
    assert matcher.match("news", [rule]) is None
    assert matcher.match("today's News briefing", [rule]) is not None


def test_static_arg_template_passes_through():
    rule = _rule(
        "r1",
        [PatternSpec("phrase", "news")],
        arg_template={"max_results": 3},
    )
    result = matcher.match("news", [rule])
    assert result is not None
    assert result.resolved_args == {"max_results": 3}
