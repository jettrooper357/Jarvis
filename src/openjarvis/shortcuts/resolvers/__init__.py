"""Resolvers map a shortcut rule's target to a normalized :class:`RawResult`."""

from __future__ import annotations

from typing import Any, Dict, Optional

from openjarvis.shortcuts._stubs import Resolver
from openjarvis.shortcuts.resolvers.datasource import DataSourceResolver
from openjarvis.shortcuts.resolvers.preset import PresetResolver
from openjarvis.shortcuts.resolvers.skill import SkillResolver
from openjarvis.shortcuts.resolvers.tool import ToolResolver


def default_resolvers(
    *,
    engine: Any = None,
    model: Optional[str] = None,
) -> Dict[str, Resolver]:
    """Return the built-in resolver map.

    ``engine`` and ``model`` are forwarded to :class:`PresetResolver` so
    its one-shot LLM call has a configured inference path; omitting them
    is supported (preset rules will return a clearly-labeled
    ``no_engine`` / ``no_model`` :class:`RawResult`).
    """
    return {
        ToolResolver.kind: ToolResolver(),
        SkillResolver.kind: SkillResolver(),
        DataSourceResolver.kind: DataSourceResolver(),
        PresetResolver.kind: PresetResolver(engine=engine, model=model),
    }


__all__ = [
    "DataSourceResolver",
    "PresetResolver",
    "SkillResolver",
    "ToolResolver",
    "default_resolvers",
]
