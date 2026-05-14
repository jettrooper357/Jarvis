"""Voice activity detection using silero-vad.

Wraps the silero-vad ONNX model behind a small streaming-friendly interface:
push 16kHz mono float32 PCM in any chunk size, get per-frame speech probabilities
plus a stateful ``in_speech`` flag that flips on the model's hysteresis-tuned
``VADIterator``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

import numpy as np

try:
    import torch
    from silero_vad import VADIterator, load_silero_vad
except ImportError:  # pragma: no cover — optional dep
    torch = None  # type: ignore[assignment]
    VADIterator = None  # type: ignore[assignment, misc]
    load_silero_vad = None  # type: ignore[assignment]


# silero-vad's 16kHz frame size. Anything else needs resampling.
_VAD_FRAME_SAMPLES = 512


@dataclass(slots=True)
class VADFrame:
    """One VAD-sized frame plus the model's decision on it."""

    audio: np.ndarray
    is_speech: bool
    speech_started: bool
    speech_ended: bool


class SileroVAD:
    """Stateful streaming VAD over 16kHz mono float32 PCM."""

    def __init__(
        self,
        *,
        threshold: float = 0.5,
        min_silence_ms: int = 700,
        speech_pad_ms: int = 100,
    ) -> None:
        if load_silero_vad is None:
            raise ImportError(
                "silero-vad is not installed. "
                "Install with: uv sync --extra speech"
            )
        self._model = load_silero_vad(onnx=False)
        self._iter = VADIterator(
            self._model,
            threshold=threshold,
            sampling_rate=16000,
            min_silence_duration_ms=min_silence_ms,
            speech_pad_ms=speech_pad_ms,
        )
        self._pending = np.zeros(0, dtype=np.float32)
        self._in_speech = False

    @property
    def in_speech(self) -> bool:
        return self._in_speech

    def feed(self, pcm: np.ndarray) -> List[VADFrame]:
        """Push float32 mono PCM at 16kHz. Returns one ``VADFrame`` per 512 samples."""
        if pcm.dtype != np.float32:
            pcm = pcm.astype(np.float32)
        buf = np.concatenate([self._pending, pcm]) if self._pending.size else pcm
        out: List[VADFrame] = []

        n_full = (buf.size // _VAD_FRAME_SAMPLES) * _VAD_FRAME_SAMPLES
        for start in range(0, n_full, _VAD_FRAME_SAMPLES):
            frame = buf[start : start + _VAD_FRAME_SAMPLES]
            tensor = torch.from_numpy(frame)
            event: Optional[dict] = self._iter(tensor, return_seconds=False)

            started = False
            ended = False
            if event is not None:
                if "start" in event:
                    self._in_speech = True
                    started = True
                if "end" in event:
                    self._in_speech = False
                    ended = True

            out.append(
                VADFrame(
                    audio=frame,
                    is_speech=self._in_speech or ended,
                    speech_started=started,
                    speech_ended=ended,
                )
            )

        self._pending = buf[n_full:]
        return out

    def reset(self) -> None:
        self._iter.reset_states()
        self._pending = np.zeros(0, dtype=np.float32)
        self._in_speech = False


__all__ = ["SileroVAD", "VADFrame"]
