"""ElevenLabs text-to-speech backend."""

from __future__ import annotations

import os
from typing import Any, List

import httpx

from openjarvis.core.registry import TTSRegistry
from openjarvis.speech.tts import TTSBackend, TTSResult

_ELEVENLABS_API_BASE = "https://api.elevenlabs.io/v1"
_DEFAULT_VOICE = "JBFqnCBsd6RMkjVDRZzb"


def _elevenlabs_synthesize(
    api_key: str,
    text: str,
    voice_id: str,
    model: str,
    output_format: str,
) -> bytes:
    eleven_format = (
        "mp3_44100_128"
        if output_format in ("", "mp3", "wav")
        else output_format
    )
    resp = httpx.post(
        f"{_ELEVENLABS_API_BASE}/text-to-speech/{voice_id}",
        params={"output_format": eleven_format},
        headers={
            "xi-api-key": api_key,
            "Accept": "audio/mpeg",
            "Content-Type": "application/json",
        },
        json={
            "text": text,
            "model_id": model,
        },
        timeout=120.0,
    )
    resp.raise_for_status()
    return resp.content


@TTSRegistry.register("elevenlabs")
class ElevenLabsTTSBackend(TTSBackend):
    """ElevenLabs cloud synthesis."""

    backend_id = "elevenlabs"

    def __init__(
        self,
        *,
        api_key: str = "",
        model: str = "eleven_multilingual_v2",
    ) -> None:
        self._api_key = api_key or os.environ.get("ELEVENLABS_API_KEY", "")
        self._model = model

    def synthesize(
        self,
        text: str,
        *,
        voice_id: str = "",
        speed: float = 1.0,
        output_format: str = "mp3",
    ) -> TTSResult:
        if not self._api_key:
            raise RuntimeError("ELEVENLABS_API_KEY not set")

        voice = voice_id or _DEFAULT_VOICE
        response_format = "mp3" if output_format in ("", "wav") else output_format
        audio = _elevenlabs_synthesize(
            self._api_key,
            text,
            voice_id=voice,
            model=self._model,
            output_format=response_format,
        )

        return TTSResult(
            audio=audio,
            format=response_format,
            voice_id=voice,
            metadata={"backend": "elevenlabs", "model": self._model, "speed": speed},
        )

    def voice_options(self) -> list[dict[str, Any]]:
        if not self._api_key:
            return []
        resp = httpx.get(
            f"{_ELEVENLABS_API_BASE}/voices",
            headers={"xi-api-key": self._api_key},
            timeout=30.0,
        )
        resp.raise_for_status()
        voices = resp.json().get("voices", [])
        return [
            {
                "id": str(v.get("voice_id") or ""),
                "name": str(v.get("name") or v.get("voice_id") or ""),
            }
            for v in voices
            if v.get("voice_id")
        ]

    def available_voices(self) -> List[str]:
        return [v["id"] for v in self.voice_options()]

    def health(self) -> bool:
        return bool(self._api_key)
