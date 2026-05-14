"""Streaming speech-to-text: VAD-segmented whisper over 16kHz PCM.

The browser sends raw int16 PCM frames over a WebSocket; the server resamples
to float32 mono, runs silero-vad per 32ms frame, and runs faster-whisper on
each detected speech segment. Partial transcripts are emitted every
``partial_interval_ms`` while speech is ongoing so the UI can show an interim
result; a final transcript is emitted when VAD detects silence.

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
        partial_interval_ms: int = 1500,
        language: Optional[str] = None,
    ) -> None:
        self._backend = backend
        self._vad = SileroVAD(
            threshold=vad_threshold,
            min_silence_ms=min_silence_ms,
        )
        self._partial_interval_samples = int(
            partial_interval_ms * _SAMPLE_RATE / 1000
        )
        self._language = language
        self._buffer: List[np.ndarray] = []
        self._samples_since_partial = 0

    def feed_int16(self, pcm: bytes) -> Iterator[TranscriptEvent]:
        """Push raw little-endian int16 PCM bytes; yield transcript events."""
        if not pcm:
            return
        arr = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
        yield from self.feed_float32(arr)

    def feed_float32(self, pcm: np.ndarray) -> Iterator[TranscriptEvent]:
        """Push float32 mono PCM at 16kHz; yield transcript events."""
        for frame in self._vad.feed(pcm):
            if frame.speech_started and not self._buffer:
                yield TranscriptEvent(type="speech_start")

            if frame.is_speech:
                self._buffer.append(frame.audio)
                self._samples_since_partial += frame.audio.size

                if (
                    self._samples_since_partial >= self._partial_interval_samples
                    and not frame.speech_ended
                ):
                    text = self._transcribe_buffer()
                    self._samples_since_partial = 0
                    if text:
                        yield TranscriptEvent(type="partial", text=text)

            if frame.speech_ended:
                text = self._transcribe_buffer()
                self._buffer.clear()
                self._samples_since_partial = 0
                yield TranscriptEvent(type="speech_end")
                if text:
                    yield TranscriptEvent(type="final", text=text, is_final=True)

    def flush(self) -> Iterator[TranscriptEvent]:
        """Force-transcribe whatever's buffered, regardless of VAD state."""
        if not self._buffer:
            return
        text = self._transcribe_buffer()
        self._buffer.clear()
        self._samples_since_partial = 0
        self._vad.reset()
        if text:
            yield TranscriptEvent(type="final", text=text, is_final=True)

    def reset(self) -> None:
        self._buffer.clear()
        self._samples_since_partial = 0
        self._vad.reset()

    def _transcribe_buffer(self) -> str:
        if not self._buffer:
            return ""
        audio = np.concatenate(self._buffer)
        model = self._backend._ensure_model()
        kwargs = {}
        if self._language:
            kwargs["language"] = self._language
        segments, _info = model.transcribe(audio, **kwargs)
        return "".join(seg.text for seg in segments).strip()


__all__ = ["StreamingTranscriber", "TranscriptEvent"]
