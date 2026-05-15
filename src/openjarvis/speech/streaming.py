"""Streaming speech-to-text: VAD-segmented whisper over 16kHz PCM.

The browser sends raw int16 PCM frames over a WebSocket; the server resamples
to float32 mono, runs silero-vad per 32ms frame, and runs faster-whisper once
on the full utterance when VAD detects the trailing silence. This is
final-only: there is no per-partial re-transcription of the growing buffer
(that was O(n²) and the dominant latency source), so the user gets a single
fast result shortly after they stop speaking.

faster-whisper's ``model.transcribe`` accepts a numpy array directly, so no
tempfile is needed in the streaming path.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Iterator, List, Optional

import numpy as np

from openjarvis.speech.faster_whisper import FasterWhisperBackend
from openjarvis.speech.vad import SileroVAD

logger = logging.getLogger(__name__)

_SAMPLE_RATE = 16000


@dataclass(slots=True)
class TranscriptEvent:
    """One event emitted by the streaming pipeline."""

    type: str  # "speech_start" | "partial" | "final" | "speech_end"
    text: str = ""
    is_final: bool = False
    confidence: Optional[float] = None


class StreamingTranscriber:
    """Stateful VAD-segmented whisper transcriber."""

    def __init__(
        self,
        backend: FasterWhisperBackend,
        *,
        vad_threshold: float = 0.5,
        min_silence_ms: int = 700,
        language: Optional[str] = None,
    ) -> None:
        self._backend = backend
        self._vad = SileroVAD(
            threshold=vad_threshold,
            min_silence_ms=min_silence_ms,
        )
        self._language = language
        self._buffer: List[np.ndarray] = []

    def feed_int16(self, pcm: bytes) -> Iterator[TranscriptEvent]:
        """Push raw little-endian int16 PCM bytes; yield transcript events."""
        if not pcm:
            return
        arr = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
        yield from self.feed_float32(arr)

    def feed_float32(self, pcm: np.ndarray) -> Iterator[TranscriptEvent]:
        """Push float32 mono PCM at 16kHz; yield transcript events.

        Final-only: audio is accumulated while VAD reports speech and the
        whole utterance is transcribed exactly once when VAD detects the
        trailing silence. No per-partial re-transcription — that was O(n²)
        over the growing buffer and was the dominant latency source.
        """
        for frame in self._vad.feed(pcm):
            if frame.speech_started and not self._buffer:
                yield TranscriptEvent(type="speech_start")

            if frame.is_speech:
                self._buffer.append(frame.audio)

            if frame.speech_ended:
                text = self._transcribe_buffer()
                self._buffer.clear()
                yield TranscriptEvent(type="speech_end")
                if text:
                    yield TranscriptEvent(type="final", text=text, is_final=True)

    def flush(self) -> Iterator[TranscriptEvent]:
        """Force-transcribe whatever's buffered, regardless of VAD state."""
        if not self._buffer:
            return
        text = self._transcribe_buffer()
        self._buffer.clear()
        self._vad.reset()
        if text:
            yield TranscriptEvent(type="final", text=text, is_final=True)

    def reset(self) -> None:
        self._buffer.clear()
        self._vad.reset()

    def _transcribe_buffer(self) -> str:
        if not self._buffer:
            return ""
        audio = np.concatenate(self._buffer)
        model = self._backend._ensure_model()
        kwargs = {
            # Greedy decode — fast and accurate enough for short voice
            # commands; beam search (default 5) is the main per-call cost.
            "beam_size": 1,
            # silero-vad already segmented this buffer; faster-whisper's own
            # VAD pass would just duplicate that work.
            "vad_filter": False,
            # Single isolated utterance — no prior context to condition on.
            "condition_on_previous_text": False,
        }
        if self._language:
            kwargs["language"] = self._language
        segments, _info = model.transcribe(audio, **kwargs)
        return "".join(seg.text for seg in segments).strip()


__all__ = ["StreamingTranscriber", "TranscriptEvent"]
