"""Pure phrase / regex / slot matcher for shortcut routing.

The matcher takes an inbound user message and a list of enabled rules and
returns at most one :class:`MatchResult`, or ``None`` when nothing matches.

Slot extraction: phrase values may contain ``{slot}`` placeholders which
are converted to non-greedy named groups (``(?P<slot>.+?)``). Regex
values can use Python ``re`` named groups directly. Extracted slot values
feed ``arg_template`` to build the target's arguments.

Safety: each pattern is matched in a worker thread with a configurable
timeout. A pattern that exceeds the budget is dropped for the current
call and the rule is flagged via :data:`_unsafe_rule_ids` so callers
(typically the :func:`openjarvis.shortcuts.try_shortcut` entry point)
can disable it durably and emit a telemetry event.
"""

from __future__ import annotations

import re
import threading
from typing import Any, Dict, Iterable, List, Optional, Pattern, Tuple

from openjarvis.shortcuts._stubs import MatchResult, PatternSpec, ShortcutRule

_SLOT_RE = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")
_PUNCT_TRIM_RE = re.compile(r"^[\s\W_]+|[\s\W_]+$", re.UNICODE)

# Per-pattern match budget. Catastrophic-backtracking regex won't return
# within this window; we abandon it and mark the parent rule unsafe.
_MATCH_TIMEOUT_SECONDS = 0.25

# Set of rule ids whose patterns blew the match budget on the current
# process. The :mod:`openjarvis.shortcuts` entry point drains this set
# after each ``match()`` call and disables the offending rules in the
# registry. Stored as a module-level set guarded by a lock so multiple
# threads can safely report.
_unsafe_rule_ids: set[str] = set()
_unsafe_lock = threading.Lock()


def drain_unsafe_rule_ids() -> List[str]:
    """Pop and return rule ids flagged unsafe since the last drain."""
    with _unsafe_lock:
        ids = list(_unsafe_rule_ids)
        _unsafe_rule_ids.clear()
    return ids


def _flag_unsafe(rule_id: str) -> None:
    with _unsafe_lock:
        _unsafe_rule_ids.add(rule_id)


def _phrase_to_regex(value: str) -> str:
    """Convert a phrase (with optional ``{slot}`` markers) to a regex.

    Literal characters are ``re.escape``-d. ``{slot}`` becomes a named
    group whose greediness depends on what follows: non-greedy when more
    literal text follows (so the slot stops at the next literal), greedy
    when the slot is the final token (so it captures the rest of the
    user message). Whitespace runs in the phrase match any whitespace
    run in the input.
    """
    matches = list(_SLOT_RE.finditer(value))
    parts: List[str] = []
    pos = 0
    for idx, m in enumerate(matches):
        literal = value[pos : m.start()]
        if literal:
            parts.append(_escape_with_flexible_ws(literal))
        is_last = idx == len(matches) - 1
        has_tail = is_last and value[m.end() :].strip() != ""
        quantifier = ".+?" if (not is_last or has_tail) else ".+"
        parts.append(f"(?P<{m.group(1)}>{quantifier})")
        pos = m.end()
    tail = value[pos:]
    if tail:
        parts.append(_escape_with_flexible_ws(tail))
    return "".join(parts)


def _escape_with_flexible_ws(literal: str) -> str:
    escaped = re.escape(literal)
    return re.sub(r"(\\\s)+", r"\\s+", escaped)


def _compile_pattern(
    rule: ShortcutRule,
    pattern: PatternSpec,
) -> Optional[Pattern[str]]:
    flags = 0 if rule.case_sensitive else re.IGNORECASE
    if pattern.kind == "regex":
        raw = pattern.value
    elif pattern.kind == "phrase":
        raw = _phrase_to_regex(pattern.value)
    else:
        return None

    if rule.match_mode == "whole_message":
        raw = rf"^\s*{raw}\s*$"
    try:
        return re.compile(raw, flags)
    except re.error:
        return None


def _normalize_for_whole_message(message: str) -> str:
    return _PUNCT_TRIM_RE.sub("", message)


def _resolve_args(
    arg_template: Dict[str, object],
    slots: Dict[str, str],
) -> Dict[str, object]:
    resolved: Dict[str, object] = {}
    for key, value in arg_template.items():
        if isinstance(value, str) and "{" in value:
            try:
                resolved[key] = value.format(**slots)
            except (KeyError, IndexError):
                resolved[key] = value
        else:
            resolved[key] = value
    return resolved


def _candidate_score(
    match_text: str,
    rule: ShortcutRule,
) -> Tuple[int, int, str, int]:
    """Sort key for ranking matches.

    Higher priority wins; then longest match; then most-recent update;
    then user-authored over system-seeded. Built so Python's ``max``
    picks the winner.
    """
    return (
        rule.priority,
        len(match_text),
        rule.updated_at or rule.created_at or "",
        1 if rule.created_by != "system" else 0,
    )


def _safe_search(
    regex: Pattern[str],
    haystack: str,
    rule_id: str,
    *,
    enforce_timeout: bool,
) -> Optional[re.Match[str]]:
    """Run ``regex.search``; enforce a timeout for user-authored regex.

    Phrase-derived patterns are compiled in this module from user-typed
    literals (plus internal ``(?P<slot>.+?)`` groups) so we can run them
    on the hot path without thread-pool overhead. User-authored regex
    goes through a worker so catastrophic backtracking can't hang the
    request.
    """

    if not enforce_timeout:
        try:
            return regex.search(haystack)
        except re.error:
            return None

    holder: Dict[str, Any] = {"match": None, "error": None}
    done = threading.Event()

    def _worker() -> None:
        try:
            holder["match"] = regex.search(haystack)
        except re.error as exc:
            holder["error"] = exc
        finally:
            done.set()

    thread = threading.Thread(
        target=_worker,
        name=f"shortcut-match-{rule_id[:8]}",
        daemon=True,
    )
    thread.start()
    if not done.wait(timeout=_MATCH_TIMEOUT_SECONDS):
        # The worker thread is still running. Flag the rule unsafe and
        # walk away — the thread is a daemon and will not block exit.
        _flag_unsafe(rule_id)
        return None
    if holder["error"] is not None:
        return None
    return holder["match"]


def match(
    message: str,
    rules: Iterable[ShortcutRule],
) -> Optional[MatchResult]:
    """Return the best :class:`MatchResult` for *message*, or ``None``."""
    if not message:
        return None

    best: Optional[Tuple[Tuple[int, int, str, int], MatchResult]] = None

    for rule in rules:
        if not rule.enabled or not rule.patterns:
            continue
        haystack = (
            _normalize_for_whole_message(message)
            if rule.match_mode == "whole_message"
            else message
        )
        for pattern in rule.patterns:
            regex = _compile_pattern(rule, pattern)
            if regex is None:
                continue
            search = _safe_search(
                regex,
                haystack,
                rule.id,
                enforce_timeout=pattern.kind == "regex",
            )
            if search is None:
                continue
            slots = {k: v for k, v in search.groupdict().items() if v is not None}
            slots = {k: v.strip() for k, v in slots.items()}
            resolved_args = _resolve_args(rule.arg_template, slots)
            result = MatchResult(
                rule=rule,
                matched_text=search.group(0),
                slots=slots,
                resolved_args=resolved_args,
            )
            score = _candidate_score(search.group(0), rule)
            if best is None or score > best[0]:
                best = (score, result)
            break

    return best[1] if best else None


__all__ = ["match"]
