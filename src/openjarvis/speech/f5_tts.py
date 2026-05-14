"""F5-TTS backend — zero-shot voice cloning from a short reference clip.

Install with::

    uv sync --extra speech-clone

The reference clip should be 6-10 seconds of clean speech. On first synthesis
the F5-TTS model (~1.4 GB) is downloaded from HuggingFace. CPU inference is
several times slower than real-time; a CUDA GPU is strongly recommended.

The ``voice_id`` parameter here is the file path of a stored reference clip
(typically managed by :mod:`openjarvis.speech.custom_voices`). The optional
``ref_text`` kwarg is the transcript of the clip — if omitted, F5-TTS uses
its bundled Whisper to transcribe it automatically.
"""

from __future__ import annotations

import io
import logging
import os
import tempfile
from pathlib import Path
from typing import Iterator, List, Optional

from openjarvis.core.registry import TTSRegistry
from openjarvis.speech.tts import TTSBackend, TTSChunk, TTSResult

logger = logging.getLogger(__name__)


def _try_import_f5():
    """Import the F5-TTS API class, supporting either layout the package has shipped."""
    try:
        from f5_tts.api import F5TTS  # type: ignore[import-not-found]

        return F5TTS
    except ImportError:
        return None


@TTSRegistry.register("f5-tts")
class F5TTSBackend(TTSBackend):
    """Local voice cloning via F5-TTS."""

    backend_id = "f5-tts"

    def __init__(
        self,
        *,
        model_type: str = "F5-TTS",
        device: str = "auto",
    ) -> None:
        self._model_type = model_type
        self._device = device
        self._instance = None

    def _ensure_instance(self):
        if self._instance is not None:
            return self._instance
        cls = _try_import_f5()
        if cls is None:
            raise RuntimeError(
                "f5-tts is not installed. Install with: uv sync --extra speech-clone"
            )
        device = None if self._device == "auto" else self._device
        # The F5TTS constructor's parameter name has shifted across releases;
        # try a couple of shapes so we don't get pinned to a specific version.
        for kwargs in (
            {"model_type": self._model_type, "device": device},
            {"model": self._model_type, "device": device},
            {"device": device},
            {},
        ):
            kwargs = {k: v for k, v in kwargs.items() if v is not None}
            try:
                self._instance = cls(**kwargs)
                logger.info("Loaded F5-TTS with kwargs=%s", kwargs)
                return self._instance
            except TypeError:
                continue
        raise RuntimeError("Failed to instantiate F5-TTS — incompatible package version?")

    def synthesize(
        self,
        text: str,
        *,
        voice_id: str = "",
        speed: float = 1.0,
        output_format: str = "wav",
        ref_text: str = "",
    ) -> TTSResult:
        if not voice_id or not os.path.exists(voice_id):
            raise RuntimeError(
                f"F5-TTS requires a reference audio path; got voice_id={voice_id!r}"
            )
        instance = self._ensure_instance()
        import numpy as np
        import soundfile as sf

        # F5-TTS writes its own output file; give it a temp path and read it back.
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            out_path = tmp.name
        try:
            wav, sr, _ = instance.infer(
                ref_file=voice_id,
                ref_text=ref_text or "",
                gen_text=text,
                file_wave=out_path,
                remove_silence=False,
                speed=speed,
            )
            if isinstance(wav, np.ndarray):
                audio_arr = wav
            else:
                audio_arr, sr = sf.read(out_path, dtype="float32", always_2d=False)
            buf = io.BytesIO()
            sf.write(buf, audio_arr, sr, format=output_format.upper())
            buf.seek(0)
            return TTSResult(
                audio=buf.read(),
                format=output_format,
                voice_id=voice_id,
                sample_rate=sr,
                duration_seconds=len(audio_arr) / sr if sr else 0.0,
                metadata={"backend": "f5-tts"},
            )
        finally:
            try:
                Path(out_path).unlink(missing_ok=True)
            except OSError:
                pass

    def stream(
        self,
        text: str,
        *,
        voice_id: str = "",
        speed: float = 1.0,
        output_format: str = "wav",
        ref_text: str = "",
    ) -> Iterator[TTSChunk]:
        """F5-TTS doesn't stream natively; split on sentence boundaries instead.

        Each segment is synthesized and yielded as a single TTSChunk so the
        browser can start playing before the entire reply is rendered. This
        keeps end-to-end latency much better than waiting for the full text.
        """
        sentences = _split_sentences(text)
        for sentence in sentences:
            if not sentence.strip():
                continue
            result = self.synthesize(
                sentence,
                voice_id=voice_id,
                speed=speed,
                output_format=output_format,
                ref_text=ref_text,
            )
            yield TTSChunk(
                audio=result.audio,
                format=result.format,
                sample_rate=result.sample_rate,
                text=sentence,
            )

    def available_voices(self) -> List[str]:
        return []

    def health(self) -> bool:
        return _try_import_f5() is not None


def _split_sentences(text: str) -> List[str]:
    out: List[str] = []
    buf = ""
    for ch in text:
        buf += ch
        if ch in ".!?\n" and len(buf.strip()) > 4:
            out.append(buf.strip())
            buf = ""
    if buf.strip():
        out.append(buf.strip())
    return out


__all__ = ["F5TTSBackend"]
