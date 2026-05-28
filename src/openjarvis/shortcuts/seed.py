"""Built-in seeded shortcut rules.

Installed on first use when ``config.shortcuts.seed_builtin_rules_on_first_run``
is true. Each seed has ``created_by="system"`` so the UI can badge them.
Users may edit or delete them freely.
"""

from __future__ import annotations

from datetime import datetime, timezone

from openjarvis.shortcuts._stubs import PatternSpec, ShortcutRule
from openjarvis.shortcuts.registry import ShortcutRegistry

_SEED_MARKER_IDS = {
    "system::news::default",
    "system::news::topic",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _build_seeds() -> list[ShortcutRule]:
    ts = _now()
    return [
        ShortcutRule(
            id="system::news::default",
            name="News briefing",
            enabled=True,
            priority=100,
            patterns=[
                PatternSpec(kind="phrase", value="what's the news"),
                PatternSpec(kind="phrase", value="whats the news"),
                PatternSpec(kind="phrase", value="today's news"),
                PatternSpec(kind="phrase", value="todays news"),
                PatternSpec(kind="phrase", value="news briefing"),
                PatternSpec(kind="phrase", value="give me the news"),
            ],
            match_mode="contains",
            case_sensitive=False,
            target_kind="tool",
            target_id="get_news",
            arg_template={},
            post_prompt=None,
            post_model=None,
            on_failure="fallback_to_chief",
            created_at=ts,
            updated_at=ts,
            created_by="system",
        ),
        ShortcutRule(
            id="system::news::topic",
            name="News about a topic",
            enabled=True,
            priority=110,
            patterns=[
                PatternSpec(
                    kind="regex", value=r"^\s*news about (?P<topic>.+?)\s*\??\s*$"
                ),
            ],
            match_mode="contains",
            case_sensitive=False,
            target_kind="tool",
            target_id="get_news",
            arg_template={"topic": "{topic}"},
            post_prompt=None,
            post_model=None,
            on_failure="fallback_to_chief",
            created_at=ts,
            updated_at=ts,
            created_by="system",
        ),
    ]


def ensure_seeded(registry: ShortcutRegistry) -> int:
    """Install missing built-in rules. Returns the number installed."""
    existing_ids = {rule.id for rule in registry.list()}
    installed = 0
    for seed in _build_seeds():
        if seed.id in existing_ids:
            continue
        registry.upsert(seed)
        installed += 1
    return installed


__all__ = ["ensure_seeded"]
