"""Kokoro TTS backend — fully open-source, runs locally.

Requires the kokoro package: pip install kokoro
Falls back gracefully if not installed.
"""

from __future__ import annotations

import io
from typing import Iterator, List

from openjarvis.core.registry import TTSRegistry
from openjarvis.speech.tts import TTSBackend, TTSChunk, TTSResult


# Voices shipped in hexgrad/Kokoro-82M v1.0. Grouped by language code prefix:
#   a = American English  b = British English  e = Spanish  f = French
#   h = Hindi             i = Italian          j = Japanese p = Portuguese
#   z = Mandarin Chinese
# Second letter: f = female, m = male.
_LANG_INSTALL_HINTS = {
    "j": "Install with: pip install 'misaki[ja]'",
    "z": "Install with: pip install 'misaki[zh]'",
    "h": "Install with: pip install 'misaki[hi]'",
    "k": "Install with: pip install 'misaki[ko]'",
}


KOKORO_VOICES: List[str] = [
    # American English — female
    "af_alloy", "af_aoede", "af_bella", "af_heart", "af_jessica",
    "af_kore", "af_nicole", "af_nova", "af_river", "af_sarah", "af_sky",
    # American English — male
    "am_adam", "am_echo", "am_eric", "am_fenrir", "am_liam",
    "am_michael", "am_onyx", "am_puck", "am_santa",
    # British English
    "bf_alice", "bf_emma", "bf_isabella", "bf_lily",
    "bm_daniel", "bm_fable", "bm_george", "bm_lewis",
    # Spanish
    "ef_dora", "em_alex", "em_santa",
    # French
    "ff_siwis",
    # Hindi
    "hf_alpha", "hf_beta", "hm_omega", "hm_psi",
    # Italian
    "if_sara", "im_nicola",
    # Japanese
    "jf_alpha", "jf_gongitsune", "jf_nezumi", "jf_tebukuro", "jm_kumo",
    # Portuguese
    "pf_dora", "pm_alex", "pm_santa",
    # Chinese
    "zf_xiaobei", "zf_xiaoni", "zf_xiaoxiao", "zf_xiaoyi",
    "zm_yunjian", "zm_yunxi", "zm_yunxia", "zm_yunyang",
]


@TTSRegistry.register("kokoro")
class KokoroTTSBackend(TTSBackend):
    """Kokoro TTS — local open-source voice synthesis."""

    backend_id = "kokoro"

    def __init__(self, *, model_path: str = "", device: str = "auto") -> None:
        self._model_path = model_path
        self._device = device
        # Per-language-code pipelines. Each KPipeline downloads its own G2P
        # weights, so we lazily create them on first use rather than loading
        # all nine at startup.
        self._pipelines: dict[str, object] = {}

    def _pipeline_for(self, voice_id: str):
        """Pick the right KPipeline for the voice's language prefix.

        Kokoro voices are named ``<lang><gender>_<name>`` (e.g. ``jf_alpha``).
        Voice mixes use a comma-separated list — we key off the first voice's
        language. If the prefix isn't recognized we use American English so
        unknown IDs still produce sound rather than crashing.
        """
        try:
            from kokoro import KPipeline
        except ImportError as exc:
            raise RuntimeError(
                "kokoro package not installed. Install with: pip install kokoro"
            ) from exc

        primary = voice_id.split(",")[0].strip() if voice_id else ""
        lang_code = primary[0] if primary and primary[0].isalpha() else "a"
        if lang_code not in self._pipelines:
            try:
                self._pipelines[lang_code] = KPipeline(lang_code=lang_code)
            except ModuleNotFoundError as exc:
                # Per-language G2P libs (pyopenjtalk for ja, cn2an/pypinyin for
                # zh, etc.) aren't pulled in by base kokoro. Surface a useful
                # hint instead of the bare import error.
                hint = _LANG_INSTALL_HINTS.get(lang_code, "")
                raise RuntimeError(
                    f"Kokoro voice {voice_id!r} needs extra language support: "
                    f"{exc.name} is missing.{(' ' + hint) if hint else ''}"
                ) from exc
        return self._pipelines[lang_code]

    def synthesize(
        self,
        text: str,
        *,
        voice_id: str = "af_heart",
        speed: float = 1.0,
        output_format: str = "wav",
    ) -> TTSResult:
        pipeline = self._pipeline_for(voice_id)
        import numpy as np
        import soundfile as sf

        samples = []
        for _, _, audio in pipeline(text, voice=voice_id, speed=speed):
            samples.append(audio)

        if not samples:
            return TTSResult(audio=b"", format=output_format, voice_id=voice_id)

        combined = np.concatenate(samples)
        buf = io.BytesIO()
        sf.write(buf, combined, 24000, format=output_format.upper())
        buf.seek(0)

        return TTSResult(
            audio=buf.read(),
            format=output_format,
            voice_id=voice_id,
            sample_rate=24000,
            duration_seconds=len(combined) / 24000,
            metadata={"backend": "kokoro"},
        )

    def stream(
        self,
        text: str,
        *,
        voice_id: str = "af_heart",
        speed: float = 1.0,
        output_format: str = "wav",
    ) -> Iterator[TTSChunk]:
        """Yield one ``TTSChunk`` per kokoro segment (≈ one sentence)."""
        pipeline = self._pipeline_for(voice_id)
        import soundfile as sf

        for graphemes, _phonemes, audio in pipeline(
            text, voice=voice_id, speed=speed
        ):
            buf = io.BytesIO()
            sf.write(buf, audio, 24000, format=output_format.upper())
            buf.seek(0)
            yield TTSChunk(
                audio=buf.read(),
                format=output_format,
                sample_rate=24000,
                text=graphemes or "",
            )

    def available_voices(self) -> List[str]:
        return list(KOKORO_VOICES)

    def health(self) -> bool:
        try:
            import kokoro  # noqa: F401

            return True
        except ImportError:
            return False
