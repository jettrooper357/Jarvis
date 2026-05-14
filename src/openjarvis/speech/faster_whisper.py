"""Faster-Whisper speech-to-text backend (local, CTranslate2-based)."""

from __future__ import annotations

import logging
import tempfile
from typing import List, Optional

from openjarvis.core.registry import SpeechRegistry
from openjarvis.speech._stubs import Segment, SpeechBackend, TranscriptionResult

try:
    from faster_whisper import WhisperModel
except ImportError:
    WhisperModel = None  # type: ignore[assignment, misc]

logger = logging.getLogger(__name__)


def _pick_compute_type(device: str, requested: str) -> tuple[str, str]:
    """Resolve (device, compute_type) against what ctranslate2 actually supports.

    The historical default ``float16`` crashes on CPU and on GPUs without
    fp16. We probe ctranslate2 and pick the best supported type instead of
    failing at first inference.
    """
    try:
        import ctranslate2
    except Exception:
        return device, requested

    cuda_count = 0
    try:
        cuda_count = ctranslate2.get_cuda_device_count()
    except Exception:
        cuda_count = 0

    resolved_device = device
    if device == "auto":
        resolved_device = "cuda" if cuda_count > 0 else "cpu"
    elif device == "cuda" and cuda_count == 0:
        logger.warning("CUDA requested but not available; falling back to CPU")
        resolved_device = "cpu"

    try:
        supported = set(ctranslate2.get_supported_compute_types(resolved_device))
    except Exception:
        supported = set()

    if not supported or requested in supported:
        return resolved_device, requested

    # Pick best available fallback for the device
    if resolved_device == "cuda":
        for candidate in ("float16", "int8_float16", "float32", "int8"):
            if candidate in supported:
                logger.warning(
                    "compute_type=%r not supported on cuda; using %r",
                    requested, candidate,
                )
                return resolved_device, candidate
    for candidate in ("int8_float32", "int8", "float32"):
        if candidate in supported:
            logger.warning(
                "compute_type=%r not supported on %s; using %r",
                requested, resolved_device, candidate,
            )
            return resolved_device, candidate
    return resolved_device, requested


@SpeechRegistry.register("faster-whisper")
class FasterWhisperBackend(SpeechBackend):
    """Local speech-to-text using Faster-Whisper (CTranslate2)."""

    backend_id = "faster-whisper"

    def __init__(
        self,
        model_size: str = "base",
        device: str = "auto",
        compute_type: str = "float16",
    ) -> None:
        self._model_size = model_size
        self._device = device
        self._compute_type = compute_type
        self._model: Optional[WhisperModel] = None

    def _ensure_model(self) -> WhisperModel:
        """Lazy-load the Whisper model on first use."""
        if self._model is None:
            if WhisperModel is None:
                raise ImportError(
                    "faster-whisper is not installed. "
                    "Install with: uv sync --extra speech"
                )
            device, compute_type = _pick_compute_type(
                self._device, self._compute_type
            )
            self._model = WhisperModel(
                self._model_size,
                device=device,
                compute_type=compute_type,
            )
            self._device = device
            self._compute_type = compute_type
        return self._model

    def transcribe(
        self,
        audio: bytes,
        *,
        format: str = "wav",
        language: Optional[str] = None,
    ) -> TranscriptionResult:
        """Transcribe audio bytes using Faster-Whisper."""
        model = self._ensure_model()

        # Write audio to a temp file (faster-whisper needs a file path)
        suffix = f".{format}" if not format.startswith(".") else format
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=True) as tmp:
            tmp.write(audio)
            tmp.flush()

            kwargs = {}
            if language:
                kwargs["language"] = language

            segments_iter, info = model.transcribe(tmp.name, **kwargs)
            segments_list = list(segments_iter)

        # Build result
        text = "".join(seg.text for seg in segments_list).strip()
        segments = [
            Segment(
                text=seg.text.strip(),
                start=seg.start,
                end=seg.end,
                confidence=None,
            )
            for seg in segments_list
        ]

        return TranscriptionResult(
            text=text,
            language=getattr(info, "language", None),
            confidence=getattr(info, "language_probability", None),
            duration_seconds=getattr(info, "duration", 0.0),
            segments=segments,
        )

    def health(self) -> bool:
        """Check if model is loaded or loadable."""
        if self._model is not None:
            return True
        return WhisperModel is not None

    def supported_formats(self) -> List[str]:
        """Supported audio formats (same as ffmpeg/Whisper)."""
        return ["wav", "mp3", "m4a", "ogg", "flac", "webm"]
