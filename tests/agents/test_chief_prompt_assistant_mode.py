from __future__ import annotations

from openjarvis.agents.templates.chief_prompt import build_chief_system_prompt


def test_flag_off_is_default_and_has_no_ea_block():
    prompt = build_chief_system_prompt()
    assert "EXECUTIVE ASSISTANT MODE" not in prompt
    # Core identity preserved.
    assert "CHIEF_ORCHESTRATOR" in prompt


def test_flag_off_matches_explicit_false():
    assert build_chief_system_prompt() == build_chief_system_prompt(
        assistant_mode=False
    )


def test_flag_on_adds_ea_block_and_preserves_core():
    prompt = build_chief_system_prompt(assistant_mode=True)
    assert "EXECUTIVE ASSISTANT MODE" in prompt
    assert "followup_add" in prompt
    assert "decision_record" in prompt
    assert "CHIEF_ORCHESTRATOR" in prompt
    assert "YOUR HIERARCHY" in prompt
