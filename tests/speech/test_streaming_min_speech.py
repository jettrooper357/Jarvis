"""Tests for the streaming min-speech gate's pure helpers.

The full feed/transcribe path needs silero-vad + faster-whisper installed
(run under `uv run pytest` in the speech extra); these cover the pure math.
"""
from __future__ import annotations

from openjarvis.speech.streaming import samples_duration_ms


def test_samples_duration_ms_one_second():
    assert samples_duration_ms(16000) == 1000.0


def test_samples_duration_ms_half_second():
    assert samples_duration_ms(8000) == 500.0


def test_samples_duration_ms_zero_rate_is_safe():
    assert samples_duration_ms(16000, 0) == 0.0


def test_short_blip_below_threshold():
    # A 100 ms blip is shorter than a 300 ms min-speech gate.
    assert samples_duration_ms(1600) < 300
